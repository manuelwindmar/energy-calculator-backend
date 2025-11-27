# Energy Calculator API

Backend API para la aplicación "Calculador de Energía y Placas Solares"

## Tecnologías

- FastAPI
- MongoDB (Motor)
- OpenAI API (para análisis de imágenes)
- Python 3.11+

## Variables de Entorno Requeridas

```
MONGO_URL=mongodb+srv://usuario:password@cluster.mongodb.net/energy_calculator
EMERGENT_LLM_KEY=tu_api_key_aqui
```

## Instalación Local

```bash
pip install -r requirements.txt
uvicorn server:app --reload
```

## Despliegue en Render

Este proyecto está configurado para desplegarse en Render.com usando el archivo `render.yaml`

1. Conecta tu repositorio en Render
2. Configura las variables de entorno
3. Render automáticamente detectará la configuración

## Endpoints

- `GET /api/health` - Verificar estado del servidor
- `POST /api/analyze-chart` - Analizar imagen con IA
- `POST /api/history` - Guardar cálculo
- `GET /api/history` - Obtener historial
- `DELETE /api/history/{id}` - Eliminar cálculo
- `POST /api/send-email` - Enviar por email
- `POST /api/generar-whatsapp-link` - Generar enlace de WhatsApp
