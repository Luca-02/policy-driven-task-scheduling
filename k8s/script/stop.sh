#!/bin/sh

echo "Stopping cluster containers..."
docker stop $(docker ps -q --filter "name=thesis-")