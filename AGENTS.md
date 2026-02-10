# Docker Status MQTT Home Assistant - Developer Notes

## Project Overview
This project monitors Docker containers and publishes their status to MQTT for Home Assistant integration. It supports SSH, Docker socket, and local command execution modes.

## Architecture
- **main.py**: Core application with DockerMQTT class
- **docker_manager.py**: Abstract base with three implementations (Socket/Command/SSH)
- **config.py**: Configuration management with env vars and CLI args
- **test_docker_manager.py**: Unit tests (only for docker_manager currently)

## Key Features
- Monitors container status (running/stopped)
- Tracks container resource metrics (CPU, memory, network, disk I/O) with ENABLE_METRICS
- Creates Home Assistant switch entities via MQTT auto-discovery
- Creates Home Assistant sensor entities for metrics when enabled
- Allows remote container control (start/stop)
- Container filtering with INCLUDE_ONLY/EXCLUDE_ONLY

## Configuration Options
- SSH_HOST, SSH_PORT, SSH_USER, SSH_PASSWORD: For remote Docker access
- MQTT_SERVER, MQTT_PORT, MQTT_USER, MQTT_PASSWORD: MQTT broker settings
- PUBLISH_INTERVAL: Status update frequency (default: 60s)
- INCLUDE_ONLY: Comma-separated list of containers to monitor
- EXCLUDE_ONLY: Comma-separated list of containers to ignore
- ENABLE_METRICS: Enable container resource metrics (CPU, memory, network, disk)

## Development Commands
```bash
# Run tests
uv run pytest test_docker_manager.py

# Build Docker image
docker build -t docker-status-mqtt-homeassistant .

# Run with docker-compose
docker-compose up -d

# Check logs
docker logs docker-status-mqtt-homeassistant
```

## Known Issues & Improvements Needed
1. **Language**: Mix of Spanish/English in logs - standardize to English
2. **Architecture**: Consider async (asyncio/aiomqtt) for better performance
3. **Security**: Support SSH keys instead of passwords
4. **Testing**: Need tests for main.py and config.py
5. **Features**: Could add CPU/memory metrics, container health status
6. **Documentation**: Add MQTT topic/payload documentation

## MQTT Topics
- Status: `homeassistant/switch/{entity_prefix}{container_name}/state`
- Command: `homeassistant/switch/{entity_prefix}{container_name}/set`
- Config: `homeassistant/switch/{entity_prefix}{container_name}/config`

## Deployment
- Docker Hub: pcarorevuelta/docker-status-mqtt-homeassistant
- GitHub Actions: Automated publishing on push to main
- Unraid: XML template included for Community Applications

## Important Notes
- Always use .env.example as template
- Never commit real credentials
- Project uses `uv` for Python dependency management
- Comprehensive health checks validate MQTT, Docker API, and service status

## Health Check System
- `healthcheck.py`: Comprehensive health validation script
- Auto-detects operation mode (socket/SSH/local) and tests appropriate connectivity
- Tests MQTT connectivity, Docker API access, process health, and service activity
- Creates heartbeat file in `/tmp/docker-status-mqtt-heartbeat` for activity tracking
- Runs every 60s with 30s timeout and 3 retry attempts

## Multi-Architecture Support
- Docker images are built for both **linux/amd64** and **linux/arm64**
- GitHub Actions workflow automatically builds and publishes multi-arch images
- Docker Compose supports platform specifications for local builds
- Users on ARM devices (Raspberry Pi, etc.) can use the same image

## Container Metrics System
- **ENABLE_METRICS**: Optional feature to track resource usage
- **Supported Metrics**: CPU %, memory %, memory usage (MB), network RX/TX (MB), disk read/write (MB)
- **Home Assistant Integration**: Creates sensor entities with appropriate device classes and state classes
- **Multi-Mode Support**: Works with Docker socket, SSH, and local command execution
- **Performance**: Metrics collected only for running containers during regular status updates
- **Change Detection**: Only publishes values when they change (threshold: 0.01 for metrics, state change for container status)
- **MQTT Optimization**: Reduces unnecessary MQTT traffic by tracking previous values

## Future Enhancements Priority
1. Add comprehensive test coverage for main.py and config.py
2. Async architecture with aiomqtt/aiodocker for better performance
