from fastapi import FastAPI, Request, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import logging
import asyncio
from typing import Optional

logger = logging.getLogger(__name__)

class WebServer:
    def __init__(self, docker_mqtt_service, host="0.0.0.0", port=8080):
        self.service = docker_mqtt_service
        self.host = host
        self.port = port
        self.app = FastAPI(title="Docker Status MQTT")
        self.templates = Jinja2Templates(directory="templates")
        
        # Mount routes
        self.app.get("/", response_class=HTMLResponse)(self.read_root)
        self.app.get("/api/status")(self.get_status)
        self.app.post("/api/config")(self.update_config)
        self.app.post("/api/container/{container_name}/update")(self.update_container_status)
        # self.app.post("/api/container/{container_name}/toggle")(self.toggle_container)
        
    async def start(self):
        # Disable signal handlers in uvicorn as we handle them in main
        config = uvicorn.Config(self.app, host=self.host, port=self.port, log_level="info")
        server = uvicorn.Server(config)
        
        # Override install_signal_handlers to do nothing
        server.install_signal_handlers = lambda: None
        
        logger.info(f"Iniciando servidor web en http://{self.host}:{self.port}")
        await server.serve()

    async def read_root(self, request: Request):
        return self.templates.TemplateResponse("index.html", {
            "request": request,
            "service": self.service,
            "config": self.service.config
        })

    async def get_status(self):
        return {
            "mqtt_connected": self.service.client and self.service.client.is_connected if hasattr(self.service, 'client') else False,
            "containers": self.service.known_docker_statuses,
            "metrics": self.service.known_container_metrics
        }

    async def update_config(self, 
                          mqtt_server: str = Form(...),
                          mqtt_port: int = Form(...),
                          mqtt_user: Optional[str] = Form(None),
                          mqtt_password: Optional[str] = Form(None)):
        # This is tricky because changing config might require restarting services
        # For now, let's just log it
        logger.info(f"Config update requested: {mqtt_server}:{mqtt_port}")
        return {"status": "not_implemented_yet"}

    # async def toggle_container(self, container_name: str, action: str = Form(...)):
    #     logger.info(f"Web UI requesting {action} for {container_name}")
    #     await self.service.execute_command(action, container_name)
    #     return {"status": "ok", "container": container_name, "action": action}

    async def update_container_status(self, container_name: str):
        """Force update of a specific container's status"""
        logger.info(f"Web UI requesting status update for {container_name}")
        
        # Get status
        loop = asyncio.get_running_loop()
        container_status = await loop.run_in_executor(
            self.service.executor,
            self.service.docker_manager.get_container_status,
            container_name
        )
        
        # Update MQTT
        if self.service.docker_manager.is_container_incuded(container_name):
            await self.service.update_entity_status(container_name, container_status)
            
            # If running and metrics enabled, update metrics too
            if container_status.lower() == "running" and self.service.config.enable_metrics:
                await self.service.update_container_metrics(container_name)

        return {
            "status": "ok", 
            "container": container_name, 
            "state": container_status,
            "metrics": self.service.known_container_metrics.get(container_name, {})
        }
