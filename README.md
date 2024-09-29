# Docker Status MQTT

This is a script that publishes the status of your Docker containers to an MQTT broker, allowing you to integrate it with home automation systems like Home Assistant. It can connect to a remote Docker host via SSH or interface directly with the Docker socket.

This was created for my Unraid server, but should work with any Docker host.

## Features

- Publishes container statuses (running or off) to MQTT.
- Dynamically creates and removes entities in Home Assistant.
- Allows starting and stopping containers via MQTT commands.
- Supports remote Docker hosts via SSH.
- Configurable update interval and MQTT credentials.

## Usage

You can use the [image hosted on docker hub](https://hub.docker.com/repository/docker/pcarorevuelta/docker-status-mqtt-homeassistant/)

1. Configure:

    Copy the `.env.example` file to `.env` and fill in your MQTT broker details, credentials, and optional SSH settings.

2. Run the Docker container using docker or docker-compose:

    ```bash
    docker run -d --name docker-status-mqtt-homeassistant --env-file .env pcarorevuelta/docker-status-mqtt-homeassistant
    ```

    ```bash
    docker-compose up -d
    ```

## Configuration

The script is configured using environment variables stored in the `.env` file:

- `SSH_HOST`: IP address or hostname of the remote Unraid server (optional, for SSH mode).
- `SSH_PORT`: SSH port of the remote Unraid server (default: 22).
- `SSH_USER`: Username for SSH connection.
- `SSH_PASSWORD`: Password for SSH connection.
- `MQTT_URL`: IP address or hostname of the MQTT broker.
- `MQTT_PORT`: Port of the MQTT broker (default: 1883).
- `MQTT_USER`: Username for MQTT authentication.
- `MQTT_PASSWORD`: Password for MQTT authentication.
- `PUBLISH_INTERVAL`: Interval in seconds for publishing container statuses (default: 60).

## Home Assistant Integration

Once the script is running and connected to your MQTT broker, you can add it to Home Assistant:

1. Make sure you have the MQTT integration set up in Home Assistant.
2. The script will automatically publish entities for your containers to the `homeassistant/switch` topic.
3. You can then add these entities to your Home Assistant dashboard.

## Contributing

Pull requests are welcome. For major changes, please open an issue first to discuss what you would like to change.

## License

[MIT](https://choosealicense.com/licenses/mit/)
