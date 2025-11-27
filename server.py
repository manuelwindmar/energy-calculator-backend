from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Optional
from datetime import datetime
import os
from dotenv import load_dotenv
from emergentintegrations.llm.chat import LlmChat, UserMessage, ImageContent
import json
import re
import aiosmtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
import base64

load_dotenv()

app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# MongoDB setup
MONGO_URL = os.getenv("MONGO_URL", "mongodb://localhost:27017")
client = AsyncIOMotorClient(MONGO_URL)
db = client.energy_calculator
calculations_collection = db.calculations

# Models
class AnalyzeRequest(BaseModel):
    image_base64: str

class SaveCalculationRequest(BaseModel):
    nombre: str
    telefono: str
    direccion: str
    periodo_desde: str
    periodo_hasta: str
    imagen_base64: str
    etiquetas: List[str]
    valores: List[float]
    total_consumo: float
    horas_sol_estandar: float
    horas_sol_calculadas: float
    factor_placas: float
    total_placas: float

class SMTPConfig(BaseModel):
    smtp_host: str
    smtp_port: str
    smtp_user: str
    smtp_password: str

class SendEmailRequest(BaseModel):
    email_destino: str
    calculo_ids: List[str]
    smtp_config: SMTPConfig

class SendWhatsAppRequest(BaseModel):
    telefono: str
    calculo_ids: List[str]

class CalculoLocal(BaseModel):
    id: str
    nombre: str
    telefono: str
    direccion: str
    periodo_desde: str
    periodo_hasta: str
    imagen_base64: str
    etiquetas: List[str]
    valores: List[float]
    total_consumo: float
    horas_sol_estandar: float
    horas_sol_calculadas: float
    factor_placas: float
    total_placas: float

class SendEmailLocalRequest(BaseModel):
    email_destino: str
    calculos: List[CalculoLocal]
    smtp_config: SMTPConfig

class SendWhatsAppLocalRequest(BaseModel):
    telefono: str
    calculos: List[CalculoLocal]

@app.get("/api/health")
async def health():
    return {"status": "healthy"}

@app.post("/api/analyze-chart")
async def analyze_chart(request: AnalyzeRequest):
    try:
        # Get API key
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="API key no configurada")
        
        # Create chat instance with OpenAI Vision
        chat = LlmChat(
            api_key=api_key,
            session_id=f"chart_analysis_{datetime.now().timestamp()}",
            system_message="Eres un asistente experto en análisis de gráficas. Extrae datos de gráficas de columnas con precisión."
        ).with_model("openai", "gpt-4o")
        
        # Create image content
        image_content = ImageContent(image_base64=request.image_base64)
        
        # Create message with specific instructions
        user_message = UserMessage(
            text="""Analiza esta gráfica de barras/columnas.

Extrae la siguiente información en formato JSON:
1. Las 13 ETIQUETAS que aparecen en la PARTE INFERIOR de cada columna (eje X)
2. Los 13 VALORES NUMÉRICOS EXACTOS que aparecen en la PARTE SUPERIOR de cada columna

CRÍTICO - VALORES EXACTOS:
- Debe haber exactamente 13 etiquetas y 13 valores
- Los valores deben ser EXACTAMENTE como aparecen en la imagen
- NO redondees ni modifiques los valores
- Si un valor tiene 4 dígitos (ejemplo: 1680, 1930), debes extraerlo COMPLETO
- Si tiene coma como separador de miles (1,680), elimina la coma y devuelve el número completo (1680)
- Mantén el orden de izquierda a derecha

Responde SOLO con este formato JSON:
{
  "etiquetas": ["etiqueta1", "etiqueta2", ...],
  "valores": [1680, 1930, 1608, ...]
}

Ejemplo: Si ves "1,680" en la columna, debes devolver 1680 (número completo de 4 dígitos).""",
            file_contents=[image_content]
        )
        
        # Send message and get response
        response = await chat.send_message(user_message)
        
        # Parse response
        try:
            # Try to extract JSON from response
            json_match = re.search(r'\{[^}]+\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group(0))
                etiquetas = data.get("etiquetas", [])
                valores = data.get("valores", [])
            else:
                raise ValueError("No JSON found")
        except:
            # Fallback: extract numbers and assume default labels
            numbers = re.findall(r'\d+[,\d]*', response)
            valores = [float(n.replace(',', '')) for n in numbers[:13]]
            etiquetas = [f"Col {i+1}" for i in range(13)]
        
        # Ensure we have exactly 13 values
        if len(valores) < 13:
            valores.extend([0] * (13 - len(valores)))
        valores = valores[:13]
        
        if len(etiquetas) < 13:
            etiquetas.extend([f"Col {i+1}" for i in range(len(etiquetas), 13)])
        etiquetas = etiquetas[:13]
        
        # Calculate sum
        suma_total = sum(valores)
        
        return {
            "etiquetas": etiquetas,
            "valores": valores,
            "suma_total": suma_total,
            "raw_response": response
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al analizar la imagen: {str(e)}")

@app.post("/api/calculos")
async def save_calculation(request: SaveCalculationRequest):
    try:
        calculation = {
            "nombre": request.nombre,
            "telefono": request.telefono,
            "direccion": request.direccion,
            "periodo_desde": request.periodo_desde,
            "periodo_hasta": request.periodo_hasta,
            "fecha": datetime.now().isoformat(),
            "imagen_base64": request.imagen_base64,
            "etiquetas": request.etiquetas,
            "valores": request.valores,
            "total_consumo": request.total_consumo,
            "horas_sol_estandar": request.horas_sol_estandar,
            "horas_sol_calculadas": request.horas_sol_calculadas,
            "factor_placas": request.factor_placas,
            "total_placas": request.total_placas
        }
        
        result = await calculations_collection.insert_one(calculation)
        
        return {"message": "Cálculo guardado exitosamente", "id": str(result.inserted_id)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al guardar el cálculo: {str(e)}")

@app.get("/api/calculos")
async def get_calculations(search: Optional[str] = None):
    try:
        calculations = []
        
        # Build query
        query = {}
        if search:
            query = {
                "$or": [
                    {"nombre": {"$regex": search, "$options": "i"}},
                    {"telefono": {"$regex": search, "$options": "i"}}
                ]
            }
        
        cursor = calculations_collection.find(query).sort("fecha", -1).limit(50)
        
        async for doc in cursor:
            calculations.append({
                "id": str(doc["_id"]),
                "nombre": doc["nombre"],
                "telefono": doc["telefono"],
                "direccion": doc["direccion"],
                "periodo_desde": doc.get("periodo_desde", ""),
                "periodo_hasta": doc.get("periodo_hasta", ""),
                "fecha": doc["fecha"],
                "imagen_base64": doc.get("imagen_base64", ""),
                "etiquetas": doc.get("etiquetas", []),
                "valores": doc.get("valores", []),
                "total_consumo": doc["total_consumo"],
                "horas_sol_estandar": doc["horas_sol_estandar"],
                "horas_sol_calculadas": doc["horas_sol_calculadas"],
                "factor_placas": doc["factor_placas"],
                "total_placas": doc["total_placas"]
            })
        
        return {"calculations": calculations}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al obtener el historial: {str(e)}")

@app.delete("/api/calculos/{calculation_id}")
async def delete_calculation(calculation_id: str):
    try:
        from bson import ObjectId
        result = await calculations_collection.delete_one({"_id": ObjectId(calculation_id)})
        
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Cálculo no encontrado")
        
        return {"message": "Cálculo eliminado exitosamente"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al eliminar el cálculo: {str(e)}")

@app.post("/api/send-email")
async def send_email(request: SendEmailRequest):
    try:
        from bson import ObjectId
        
        # Obtener los cálculos
        calculos = []
        for calculo_id in request.calculo_ids:
            calculo = await calculations_collection.find_one({"_id": ObjectId(calculo_id)})
            if calculo:
                calculos.append(calculo)
        
        if not calculos:
            raise HTTPException(status_code=404, detail="No se encontraron cálculos")
        
        # Crear el mensaje
        msg = MIMEMultipart()
        msg['From'] = request.smtp_config.smtp_user
        msg['To'] = request.email_destino
        msg['Subject'] = f"Cálculo de Placas Solares - {calculos[0]['nombre']}"
        
        # Cuerpo del email (sin emojis para evitar problemas de codificación)
        body = f"""
        <html>
        <head>
            <meta charset="UTF-8">
        </head>
        <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f8fafc;">
            <h2 style="color: #2563eb;">CALCULO DE PLACAS SOLARES</h2>
        """
        
        for calculo in calculos:
            # Obtener etiquetas y valores
            etiquetas = calculo.get('etiquetas', [])
            valores = calculo.get('valores', [])
            
            body += f"""
            <div style="border: 2px solid #e2e8f0; border-radius: 8px; padding: 20px; margin: 20px 0; background-color: white;">
                <h3 style="color: #059669;">Cliente: {calculo['nombre']}</h3>
                <p><strong>Telefono:</strong> {calculo['telefono']}</p>
                <p><strong>Direccion:</strong> {calculo['direccion']}</p>
                <p><strong>Periodo:</strong> {calculo.get('periodo_desde', 'N/A')} hasta {calculo.get('periodo_hasta', 'N/A')}</p>
                
                <hr style="border: 1px solid #e2e8f0; margin: 20px 0;">
                
                <h4 style="color: #1e293b;">VALORES DE CONSUMO MENSUAL:</h4>
                <table style="width: 100%; border-collapse: collapse; margin: 10px 0;">
            """
            
            # Agregar los 13 valores en una tabla
            for i in range(len(valores)):
                etiqueta = etiquetas[i] if i < len(etiquetas) else f"Mes {i+1}"
                valor = valores[i]
                bg_color = "#f8fafc" if i % 2 == 0 else "white"
                body += f"""
                    <tr style="background-color: {bg_color};">
                        <td style="padding: 8px; border: 1px solid #e2e8f0;"><strong>{etiqueta}</strong></td>
                        <td style="padding: 8px; border: 1px solid #e2e8f0; text-align: right;">{valor:.2f} KWh</td>
                    </tr>
                """
            
            body += f"""
                </table>
                
                <hr style="border: 1px solid #e2e8f0; margin: 20px 0;">
                
                <h4 style="color: #1e293b;">TOTALES Y CALCULOS:</h4>
                <table style="width: 100%; margin: 10px 0;">
                    <tr>
                        <td style="padding: 5px;"><strong>Total de Consumo:</strong></td>
                        <td style="padding: 5px; text-align: right;">{calculo['total_consumo']:.2f} KWh</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px;"><strong>Horas de Sol Estandar:</strong></td>
                        <td style="padding: 5px; text-align: right;">{calculo['horas_sol_estandar']:.2f}</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px;"><strong>Horas de Sol Calculadas:</strong></td>
                        <td style="padding: 5px; text-align: right;">{calculo['horas_sol_calculadas']:.2f}</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px;"><strong>Factor de Placas:</strong></td>
                        <td style="padding: 5px; text-align: right;">{calculo['factor_placas']:.2f}</td>
                    </tr>
                </table>
                
                <div style="background-color: #059669; color: white; padding: 20px; border-radius: 8px; text-align: center; margin: 20px 0;">
                    <h2 style="margin: 0; color: white;">TOTAL DE PLACAS RECOMENDADAS</h2>
                    <h1 style="margin: 10px 0; font-size: 48px; color: white;">{calculo['total_placas']:.2f}</h1>
                </div>
                
                <p style="color: #64748b; font-size: 14px; margin-top: 20px;">
                    <strong>NOTA:</strong> La imagen de la grafica esta adjunta a este correo.
                </p>
            </div>
            """
        
        body += """
        </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        # Adjuntar imágenes
        for idx, calculo in enumerate(calculos):
            if calculo.get('imagen_base64'):
                try:
                    image_data = base64.b64decode(calculo['imagen_base64'])
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(image_data)
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename="grafica_{idx+1}.jpg"')
                    msg.attach(part)
                except:
                    pass
        
        # Enviar el email usando las credenciales del usuario
        try:
            smtp_port = int(request.smtp_config.smtp_port)
            await aiosmtplib.send(
                msg,
                hostname=request.smtp_config.smtp_host,
                port=smtp_port,
                username=request.smtp_config.smtp_user,
                password=request.smtp_config.smtp_password,
                start_tls=True
            )
            
            return {
                "message": "Email enviado exitosamente",
                "email_destino": request.email_destino,
                "calculos_enviados": len(calculos)
            }
        except aiosmtplib.SMTPException as smtp_error:
            raise HTTPException(
                status_code=500, 
                detail=f"Error SMTP: {str(smtp_error)}. Verifica tus credenciales de email en la configuración."
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al enviar email: {str(e)}")

@app.post("/api/generar-whatsapp-link")
async def generar_whatsapp_link(request: SendWhatsAppRequest):
    try:
        from bson import ObjectId
        
        # Obtener los cálculos
        calculos = []
        for calculo_id in request.calculo_ids:
            calculo = await calculations_collection.find_one({"_id": ObjectId(calculo_id)})
            if calculo:
                calculos.append(calculo)
        
        if not calculos:
            raise HTTPException(status_code=404, detail="No se encontraron cálculos")
        
        # Crear mensaje para WhatsApp (sin emojis para evitar problemas de codificación)
        mensaje = "*CALCULO DE PLACAS SOLARES*\n\n"
        
        for calculo in calculos:
            mensaje += f"*Cliente:* {calculo['nombre']}\n"
            mensaje += f"*Telefono:* {calculo['telefono']}\n"
            mensaje += f"*Direccion:* {calculo['direccion']}\n"
            mensaje += f"*Periodo:* {calculo.get('periodo_desde', 'N/A')} hasta {calculo.get('periodo_hasta', 'N/A')}\n\n"
            
            # Agregar los 13 valores de las columnas
            mensaje += "*VALORES DE CONSUMO MENSUAL:*\n"
            etiquetas = calculo.get('etiquetas', [])
            valores = calculo.get('valores', [])
            
            for i in range(len(valores)):
                etiqueta = etiquetas[i] if i < len(etiquetas) else f"Mes {i+1}"
                valor = valores[i]
                mensaje += f"{etiqueta}: {valor:.2f} KWh\n"
            
            mensaje += f"\n*TOTALES Y CALCULOS:*\n"
            mensaje += f"Total de Consumo: {calculo['total_consumo']:.2f} KWh\n"
            mensaje += f"Horas de Sol Estandar: {calculo['horas_sol_estandar']:.2f}\n"
            mensaje += f"Horas de Sol Calculadas: {calculo['horas_sol_calculadas']:.2f}\n"
            mensaje += f"Factor de Placas: {calculo['factor_placas']:.2f}\n\n"
            mensaje += f"*TOTAL DE PLACAS RECOMENDADAS: {calculo['total_placas']:.2f}*\n\n"
            mensaje += f"*NOTA:* La imagen de la grafica esta disponible en el historial de la aplicacion.\n\n"
            mensaje += "-------------------\n\n"
        
        # Limpiar número de teléfono
        telefono_limpio = request.telefono.replace("+", "").replace(" ", "").replace("-", "")
        
        # Crear enlace de WhatsApp
        from urllib.parse import quote
        mensaje_encoded = quote(mensaje)
        whatsapp_link = f"https://wa.me/{telefono_limpio}?text={mensaje_encoded}"
        
        return {
            "whatsapp_link": whatsapp_link,
            "telefono": telefono_limpio,
            "calculos_incluidos": len(calculos)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar enlace de WhatsApp: {str(e)}")

@app.post("/api/send-email-local")
async def send_email_local(request: SendEmailLocalRequest):
    try:
        calculos = [calc.dict() for calc in request.calculos]
        
        if not calculos:
            raise HTTPException(status_code=404, detail="No se encontraron cálculos")
        
        # Crear el mensaje
        msg = MIMEMultipart()
        msg['From'] = request.smtp_config.smtp_user
        msg['To'] = request.email_destino
        msg['Subject'] = f"Cálculo de Placas Solares - {calculos[0]['nombre']}"
        
        # Cuerpo del email
        body = f"""
        <html>
        <head>
            <meta charset="UTF-8">
        </head>
        <body style="font-family: Arial, sans-serif; padding: 20px; background-color: #f8fafc;">
            <h2 style="color: #2563eb;">CALCULO DE PLACAS SOLARES</h2>
        """
        
        for calculo in calculos:
            etiquetas = calculo.get('etiquetas', [])
            valores = calculo.get('valores', [])
            
            body += f"""
            <div style="border: 2px solid #e2e8f0; border-radius: 8px; padding: 20px; margin: 20px 0; background-color: white;">
                <h3 style="color: #059669;">Cliente: {calculo['nombre']}</h3>
                <p><strong>Telefono:</strong> {calculo['telefono']}</p>
                <p><strong>Direccion:</strong> {calculo['direccion']}</p>
                <p><strong>Periodo:</strong> {calculo.get('periodo_desde', 'N/A')} hasta {calculo.get('periodo_hasta', 'N/A')}</p>
                
                <hr style="border: 1px solid #e2e8f0; margin: 20px 0;">
                
                <h4 style="color: #1e293b;">VALORES DE CONSUMO MENSUAL:</h4>
                <table style="width: 100%; border-collapse: collapse; margin: 10px 0;">
            """
            
            for i in range(len(valores)):
                etiqueta = etiquetas[i] if i < len(etiquetas) else f"Mes {i+1}"
                valor = valores[i]
                bg_color = "#f8fafc" if i % 2 == 0 else "white"
                body += f"""
                    <tr style="background-color: {bg_color};">
                        <td style="padding: 8px; border: 1px solid #e2e8f0;"><strong>{etiqueta}</strong></td>
                        <td style="padding: 8px; border: 1px solid #e2e8f0; text-align: right;">{valor:.2f} KWh</td>
                    </tr>
                """
            
            body += f"""
                </table>
                
                <hr style="border: 1px solid #e2e8f0; margin: 20px 0;">
                
                <h4 style="color: #1e293b;">TOTALES Y CALCULOS:</h4>
                <table style="width: 100%; margin: 10px 0;">
                    <tr>
                        <td style="padding: 5px;"><strong>Total de Consumo:</strong></td>
                        <td style="padding: 5px; text-align: right;">{calculo['total_consumo']:.2f} KWh</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px;"><strong>Horas de Sol Estandar:</strong></td>
                        <td style="padding: 5px; text-align: right;">{calculo['horas_sol_estandar']:.2f}</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px;"><strong>Horas de Sol Calculadas:</strong></td>
                        <td style="padding: 5px; text-align: right;">{calculo['horas_sol_calculadas']:.2f}</td>
                    </tr>
                    <tr>
                        <td style="padding: 5px;"><strong>Factor de Placas:</strong></td>
                        <td style="padding: 5px; text-align: right;">{calculo['factor_placas']:.2f}</td>
                    </tr>
                </table>
                
                <div style="background-color: #059669; color: white; padding: 20px; border-radius: 8px; text-align: center; margin: 20px 0;">
                    <h2 style="margin: 0; color: white;">TOTAL DE PLACAS RECOMENDADAS</h2>
                    <h1 style="margin: 10px 0; font-size: 48px; color: white;">{calculo['total_placas']:.2f}</h1>
                </div>
                
                <p style="color: #64748b; font-size: 14px; margin-top: 20px;">
                    <strong>NOTA:</strong> La imagen de la grafica esta adjunta a este correo.
                </p>
            </div>
            """
        
        body += """
        </body>
        </html>
        """
        
        msg.attach(MIMEText(body, 'html'))
        
        # Adjuntar imágenes
        for idx, calculo in enumerate(calculos):
            if calculo.get('imagen_base64'):
                try:
                    image_data = base64.b64decode(calculo['imagen_base64'])
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(image_data)
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename="grafica_{idx+1}.jpg"')
                    msg.attach(part)
                except:
                    pass
        
        # Enviar el email usando las credenciales del usuario
        try:
            smtp_port = int(request.smtp_config.smtp_port)
            await aiosmtplib.send(
                msg,
                hostname=request.smtp_config.smtp_host,
                port=smtp_port,
                username=request.smtp_config.smtp_user,
                password=request.smtp_config.smtp_password,
                start_tls=True
            )
            
            return {
                "message": "Email enviado exitosamente",
                "email_destino": request.email_destino,
                "calculos_enviados": len(calculos)
            }
        except aiosmtplib.SMTPException as smtp_error:
            raise HTTPException(
                status_code=500, 
                detail=f"Error SMTP: {str(smtp_error)}. Verifica tus credenciales de email en la configuración."
            )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al enviar email: {str(e)}")

@app.post("/api/generar-whatsapp-link-local")
async def generar_whatsapp_link_local(request: SendWhatsAppLocalRequest):
    try:
        calculos = [calc.dict() for calc in request.calculos]
        
        if not calculos:
            raise HTTPException(status_code=404, detail="No se encontraron cálculos")
        
        # Crear mensaje para WhatsApp
        mensaje = "*CALCULO DE PLACAS SOLARES*\n\n"
        
        for calculo in calculos:
            mensaje += f"*Cliente:* {calculo['nombre']}\n"
            mensaje += f"*Telefono:* {calculo['telefono']}\n"
            mensaje += f"*Direccion:* {calculo['direccion']}\n"
            mensaje += f"*Periodo:* {calculo.get('periodo_desde', 'N/A')} hasta {calculo.get('periodo_hasta', 'N/A')}\n\n"
            
            # Agregar los 13 valores de las columnas
            mensaje += "*VALORES DE CONSUMO MENSUAL:*\n"
            etiquetas = calculo.get('etiquetas', [])
            valores = calculo.get('valores', [])
            
            for i in range(len(valores)):
                etiqueta = etiquetas[i] if i < len(etiquetas) else f"Mes {i+1}"
                valor = valores[i]
                mensaje += f"{etiqueta}: {valor:.2f} KWh\n"
            
            mensaje += f"\n*TOTALES Y CALCULOS:*\n"
            mensaje += f"Total de Consumo: {calculo['total_consumo']:.2f} KWh\n"
            mensaje += f"Horas de Sol Estandar: {calculo['horas_sol_estandar']:.2f}\n"
            mensaje += f"Horas de Sol Calculadas: {calculo['horas_sol_calculadas']:.2f}\n"
            mensaje += f"Factor de Placas: {calculo['factor_placas']:.2f}\n\n"
            mensaje += f"*TOTAL DE PLACAS RECOMENDADAS: {calculo['total_placas']:.2f}*\n\n"
            mensaje += f"*NOTA:* La imagen de la grafica esta disponible en el historial de la aplicacion.\n\n"
            mensaje += "-------------------\n\n"
        
        # Limpiar número de teléfono
        telefono_limpio = request.telefono.replace("+", "").replace(" ", "").replace("-", "")
        
        # Crear enlace de WhatsApp
        from urllib.parse import quote
        mensaje_encoded = quote(mensaje)
        whatsapp_link = f"https://wa.me/{telefono_limpio}?text={mensaje_encoded}"
        
        return {
            "whatsapp_link": whatsapp_link,
            "telefono": telefono_limpio,
            "calculos_incluidos": len(calculos)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error al generar enlace de WhatsApp: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8001)