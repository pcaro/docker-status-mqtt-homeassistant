#!/usr/bin/env python3
"""
Async version of Docker Status MQTT Home Assistant integration
Uses aiomqtt and aiodocker for asynchronous operations
"""

import argparse
import asyncio
import json
import logging
import sys
from typing import Dict, Optional

import aiomqtt

from config import Config

# Configure logging
log_formatter = logging.Formatter(
    "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

stdout_handler = logging.StreamHandler(sys.stdout)
stdout_handler.setFormatter(log_formatter)

logger = logging.getLogger()
logger.addHandler(stdout_handler)
logger.setLevel(logging.INFO)


class AsyncDockerMQTT:
    """Async version of DockerMQTT using aiomqtt and aiodocker"""

    def __init__(self, config: Config):
        self.config = config
        self.prefix = config.entity_prefix
        self.device_config = {
            "identifiers": [f"{self.prefix}containers"],
            "name": f"{config.entity_name} Containers",
            "model": "Docker Containers",
            "manufacturer": "Docker Container Manager",
        }

        self.known_docker_statuses: Dict[str, str] = {}
        self.docker_manager = None
        self._shutdown_event = asyncio.Event()
        self._tasks = set()

    async def start(self):
        """Start the async application"""
        try:
            # Initialize docker manager
            self.docker_manager = await self._get_async_docker_manager()

            # Start main tasks concurrently
            tasks = [
                self._mqtt_handler(),
                self._status_updater(),
                self._heartbeat_updater(),
            ]

            # Run all tasks concurrently
            await asyncio.gather(*tasks, return_exceptions=True)

        except KeyboardInterrupt:
            logger.info("Keyboard interrupt detected. Shutting down.")
        except Exception as e:
            logger.critical(f"Critical error in main application: {str(e)}")
        finally:
            await self._cleanup()

    async def _get_async_docker_manager(self):
        """Get the appropriate async Docker manager based on configuration"""
        mode = self.config.mode()

        if mode == "socket":
            from docker_manager_async import AsyncDockerSocketManager

            return AsyncDockerSocketManager(
                include_only=self.config.include_only, exclude=self.config.exclude_only
            )
        elif mode == "ssh":
            from docker_manager_async import AsyncDockerCommandManager
            from docker_manager_async import AsyncSSHCommandExecutor

            executor = AsyncSSHCommandExecutor(
                self.config.unraid_host,
                self.config.unraid_port,
                self.config.unraid_user,
                self.config.unraid_password,
            )
            return AsyncDockerCommandManager(
                executor,
                include_only=self.config.include_only,
                exclude=self.config.exclude_only,
            )
        else:  # local
            from docker_manager_async import AsyncDockerCommandManager
            from docker_manager_async import AsyncLocalCommandExecutor

            executor = AsyncLocalCommandExecutor()
            return AsyncDockerCommandManager(
                executor,
                include_only=self.config.include_only,
                exclude=self.config.exclude_only,
            )

    async def _mqtt_handler(self):
        """Handle MQTT connection and message processing"""
        while not self._shutdown_event.is_set():
            try:
                async with aiomqtt.Client(
                    hostname=self.config.mqtt_server,
                    port=self.config.mqtt_port,
                    username=self.config.mqtt_user,
                    password=self.config.mqtt_password,
                ) as client:
                    logger.info(
                        f"Connected to MQTT broker at {self.config.mqtt_server}"
                    )

                    # Subscribe to command topics
                    await client.subscribe(f"homeassistant/switch/{self.prefix}+/set")

                    # Store client reference for publishing
                    self.mqtt_client = client

                    # Process messages
                    async for message in client.messages:
                        await self._handle_mqtt_message(message)

            except Exception as e:
                logger.error(f"MQTT connection error: {e}")
                if not self._shutdown_event.is_set():
                    logger.info("Reconnecting to MQTT in 5 seconds...")
                    await asyncio.sleep(5)

    async def _handle_mqtt_message(self, message):
        """Handle incoming MQTT messages asynchronously"""
        try:
            topic = message.topic.value
            if self.prefix not in topic:
                return

            container_name = topic.split("/")[-2].replace(self.prefix, "")

            if topic.endswith("/set"):
                command = message.payload.decode()
                # Execute command in background task
                task = asyncio.create_task(
                    self._execute_command(command, container_name)
                )
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)

        except Exception as e:
            logger.error(f"Error handling MQTT message: {e}")

    async def _execute_command(self, command: str, container_name: str):
        """Execute Docker commands asynchronously"""
        logger.info(f"Command received: {command} for {container_name}")

        try:
            if command == "ON":
                logger.info(f"Starting container {container_name}")
                await self.docker_manager.start_container(container_name)
            elif command == "OFF":
                logger.info(f"Stopping container {container_name}")
                await self.docker_manager.stop_container(container_name)
            else:
                logger.warning(f"Unknown command: {command} for {container_name}")
                return

            # Wait a moment for container state to stabilize
            await asyncio.sleep(1)

            # Update status
            container_status = await self.docker_manager.get_container_status(
                container_name
            )
            if self.docker_manager.is_container_included(container_name):
                await self._update_entity_status(container_name, container_status)

            logger.info(f"Status updated for {container_name}: {container_status}")

        except Exception as e:
            logger.error(f"Error executing command {command} for {container_name}: {e}")

    async def _status_updater(self):
        """Periodically update container statuses"""
        while not self._shutdown_event.is_set():
            try:
                await self._update_entities_and_statuses()
                await asyncio.sleep(self.config.publish_interval)
            except Exception as e:
                logger.error(f"Error in status updater: {e}")
                await asyncio.sleep(5)  # Shorter retry interval on error

    async def _update_entities_and_statuses(self):
        """Update Docker entities states and create new entities if needed"""
        logger.info("Publishing Docker container status to MQTT")

        try:
            docker_statuses = await self.docker_manager.get_docker_statuses()
            last_docker_statuses = self.known_docker_statuses
            self.known_docker_statuses = docker_statuses

            running_containers = sorted(
                [c for c in docker_statuses if docker_statuses[c].lower() == "running"]
            )
            logger.info(f"Running: {','.join(running_containers)}")

            # Process containers concurrently
            tasks = []
            for container_name, container_state in docker_statuses.items():
                tasks.append(
                    self._update_entity_status(container_name, container_state)
                )
                if container_name not in last_docker_statuses:
                    tasks.append(self._create_entity(container_name))

            # Execute all updates concurrently
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)

        except Exception as e:
            logger.error(f"Error publishing container status: {e}")

    async def _create_entity(self, container_name: str):
        """Create a new Home Assistant entity for a container"""
        if not hasattr(self, "mqtt_client"):
            return

        try:
            config_topic = self._get_topic(container_name, "config")
            config_payload = {
                "name": container_name,
                "unique_id": f"{self.prefix}{container_name}",
                "state_topic": self._get_topic(container_name, "state"),
                "command_topic": self._get_topic(container_name, "set"),
                "payload_on": "ON",
                "payload_off": "OFF",
                "state_on": "running",
                "state_off": "exited",
                "device": self.device_config,
            }

            await self.mqtt_client.publish(
                config_topic, json.dumps(config_payload), retain=True
            )
            logger.info(f"Created entity for {container_name}")

        except Exception as e:
            logger.error(f"Error creating entity for {container_name}: {e}")

    async def _update_entity_status(self, container_name: str, status: str):
        """Update the status of a container entity"""
        if not hasattr(self, "mqtt_client"):
            return

        try:
            state_topic = self._get_topic(container_name, "state")
            state_value = "running" if status.lower() == "running" else "exited"

            await self.mqtt_client.publish(state_topic, state_value, retain=True)
            logger.debug(f"Updated {container_name} status: {state_value}")

        except Exception as e:
            logger.error(f"Error updating status for {container_name}: {e}")

    async def _delete_entity(self, container_name: str):
        """Delete a Home Assistant entity for a removed container"""
        if not hasattr(self, "mqtt_client"):
            return

        try:
            config_topic = self._get_topic(container_name, "config")
            await self.mqtt_client.publish(config_topic, "", retain=True)
            logger.info(f"Deleted entity for {container_name}")

        except Exception as e:
            logger.error(f"Error deleting entity for {container_name}: {e}")

    async def _heartbeat_updater(self):
        """Update heartbeat file for health checks"""
        while not self._shutdown_event.is_set():
            try:
                await self._update_heartbeat()
                await asyncio.sleep(30)  # Update heartbeat every 30 seconds
            except Exception as e:
                logger.debug(f"Error updating heartbeat: {e}")
                await asyncio.sleep(30)

    async def _update_heartbeat(self):
        """Update heartbeat file asynchronously"""
        try:
            import aiofiles
            import pathlib

            heartbeat_file = pathlib.Path("/tmp/docker-status-mqtt-heartbeat")

            # Use touch() since it's not async I/O intensive
            heartbeat_file.touch()

        except ImportError:
            # Fallback to sync if aiofiles not available
            try:
                import pathlib

                heartbeat_file = pathlib.Path("/tmp/docker-status-mqtt-heartbeat")
                heartbeat_file.touch()
            except Exception as e:
                logger.debug(f"Failed to update heartbeat: {e}")
        except Exception as e:
            logger.debug(f"Failed to update heartbeat: {e}")

    def _get_topic(self, container_name: str, topic_type: str) -> str:
        """Generate MQTT topic for a container"""
        return f"homeassistant/switch/{self.prefix}{container_name}/{topic_type}"

    async def _cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up resources")

        # Signal shutdown
        self._shutdown_event.set()

        # Wait for background tasks to complete
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

        # Close docker manager
        if self.docker_manager:
            try:
                await self.docker_manager.close()
            except Exception as e:
                logger.error(f"Error closing docker manager: {e}")

        logger.info("Cleanup completed")


def parse_args():
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Docker Status MQTT Home Assistant Integration (Async)"
    )
    parser.add_argument("--mqtt-server", help="MQTT broker hostname or IP address")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port")
    parser.add_argument("--mqtt-user", help="MQTT username")
    parser.add_argument("--mqtt-password", help="MQTT password")
    parser.add_argument("--ssh-host", help="SSH hostname for remote Docker access")
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH port")
    parser.add_argument("--ssh-user", help="SSH username")
    parser.add_argument("--ssh-password", help="SSH password")
    parser.add_argument(
        "--publish-interval",
        type=int,
        default=60,
        help="Status publish interval in seconds",
    )
    parser.add_argument(
        "--include-only", help="Comma-separated list of containers to monitor"
    )
    parser.add_argument(
        "--exclude-only", help="Comma-separated list of containers to exclude"
    )
    parser.add_argument(
        "--use-cmd-local",
        action="store_true",
        help="Use local Docker commands instead of API",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    return parser.parse_args()


async def main():
    """Main async entry point"""
    args = parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    try:
        # Parse include/exclude lists
        include_only = None
        if args.include_only:
            include_only = [s.strip() for s in args.include_only.split(",")]

        exclude_only = None
        if args.exclude_only:
            exclude_only = [s.strip() for s in args.exclude_only.split(",")]

        # Create configuration
        config = Config(
            unraid_host=args.ssh_host,
            unraid_port=args.ssh_port,
            unraid_user=args.ssh_user,
            unraid_password=args.ssh_password,
            mqtt_server=args.mqtt_server,
            mqtt_port=args.mqtt_port,
            mqtt_user=args.mqtt_user,
            mqtt_password=args.mqtt_password,
            publish_interval=args.publish_interval,
            exclude_only=exclude_only,
            include_only=include_only,
            use_cmd_local=args.use_cmd_local,
            verbose=args.verbose,
        )

        # Create and start the async service
        service = AsyncDockerMQTT(config=config)
        await service.start()

    except Exception as e:
        logger.critical(f"Application failed to start: {e}")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
