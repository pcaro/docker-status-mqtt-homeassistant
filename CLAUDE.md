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
- Creates Home Assistant switch entities via MQTT auto-discovery
- Allows remote container control (start/stop)
- Container filtering with INCLUDE_ONLY/EXCLUDE_ONLY

## Configuration Options
- SSH_HOST, SSH_PORT, SSH_USER, SSH_PASSWORD: For remote Docker access
- MQTT_SERVER, MQTT_PORT, MQTT_USER, MQTT_PASSWORD: MQTT broker settings
- PUBLISH_INTERVAL: Status update frequency (default: 60s)
- INCLUDE_ONLY: Comma-separated list of containers to monitor
- EXCLUDE_ONLY: Comma-separated list of containers to ignore

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

## Async Architecture (NEW!)
- **main_async.py**: Async version using aiomqtt and aiodocker
- **docker_manager_async.py**: Async Docker managers with concurrent operations
- Concurrent container monitoring and MQTT publishing
- Better performance for I/O-bound operations (SSH, Docker API, MQTT)
- Background task management with proper cleanup
- Available via `uv run main_async.py` or `docker-status-mqtt-async` script

## Architecture Versions
### Synchronous (Original)
- `main.py` with `paho-mqtt` and `docker` libraries
- Sequential operations with `time.sleep()` polling
- Stable, well-tested, blocking I/O

### Asynchronous (New)
- `main_async.py` with `aiomqtt` and `aiodocker` libraries  
- Concurrent operations with `asyncio.gather()`
- Better performance, non-blocking I/O

## Future Enhancements Priority
1. ✅ Async architecture with aiomqtt/aiodocker
2. Add container metrics (CPU, memory, disk, network)
3. ✅ Implement proper health checks
4. Add comprehensive test coverage
5. Support for Docker secrets/vault
6. Multi-architecture builds (ARM support)
7. SSH connection pooling for async version
8. Performance benchmarking and optimization
