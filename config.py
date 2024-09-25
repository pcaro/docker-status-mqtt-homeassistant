import os
from docker_manager import DockerCommandManager, DockerSocketManager, SSHCommandExecutor, LocalCommandExecutor

UNRAID_HOST = os.getenv("UNRAID_HOST")
UNRAID_PORT = int(os.getenv("UNRAID_PORT", 22))
UNRAID_USER = os.getenv("UNRAID_USER")
UNRAID_PASSWORD = os.getenv("UNRAID_PASSWORD")
MQTT_URL = os.getenv("MQTT_URL")
MQTT_PORT = int(os.getenv("MQTT_PORT", 1883))
MQTT_USER = os.getenv("MQTT_USER")
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD")
PUBLISH_INTERVAL = int(os.getenv("PUBLISH_INTERVAL", 60))

class Config:

    def mode(self):
        ''' Return the mode of the docker manager, 'ssh', 'local' or 'socket' '''
        if UNRAID_HOST:
            return 'ssh'
        else:
            return 'socket'

    def get_manager(self):
        mode = self.mode()
        if mode == 'ssh':
            return DockerCommandManager(SSHCommandExecutor(UNRAID_HOST, UNRAID_PORT, UNRAID_USER, UNRAID_PASSWORD))
        elif mode == 'socket':
            return DockerSocketManager()
        else:
            return DockerCommandManager(LocalCommandExecutor())