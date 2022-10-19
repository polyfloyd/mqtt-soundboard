#! /usr/bin/env python3

import asyncio
import asyncio_mqtt as aiomqtt
import logging
import sys
import yaml
import aiofiles
import aiofiles.os as os
from os.path import join
import random
import re

logging.basicConfig()
logger = logging.getLogger('soundboard')

config = None


def load_config(filename):
    with open(filename, 'r') as f:
        return yaml.load(f, Loader=yaml.Loader)


async def play_file(audio_filename):
    cmd = config['sounds']['play_cmd']
    cmd = cmd % audio_filename
    logger.debug(f'exec: {cmd}')
    proc = await asyncio.create_subprocess_shell(cmd)
    await proc.wait()


async def file_for_sound_in_dir(dir_name):
    files = await os.listdir(dir_name)

    prio_file = next((f for f in files if f.startswith('@')), None)
    if prio_file:
        await os.rename(join(dir_name, prio_file), join(dir_name, prio_file.lstrip('@')))
        return prio_file.lstrip('@')

    return random.choice([join(dir_name, f) for f in files])


async def file_for_sound(sound_name):
    sounds_dirname = config['sounds']['directory']

    sound_file = join(sounds_dirname, sound_name)
    if await os.path.isdir(sound_file):
        return await file_for_sound_in_dir(sound_file)

    for ext in ['.mp3', '.wav']:
        test = sound_file + ext
        if await os.path.exists(test):
            return test

    return None


async def try_play_sound(sound_name):
    logger.debug(f'trying to play: {sound_name}')

    filename = await file_for_sound(sound_name)
    if not filename:
        logger.debug(f'could not play {sound_name}, no suitable file')
        return

    logger.debug(f'found for {sound_name}: {filename}')
    await play_file(filename)


async def main_task(mqtt_client, topic):
    await mqtt_client.subscribe(topic)
    async with mqtt_client.filtered_messages(topic) as msgs:
        async for msg in msgs:
            sound = msg.payload.decode()
            if sound == '':
                continue
            if not re.match('^[a-zA-Z0-9]+$', sound):
                logger.debug(f'drop {sound}: regex test failed')
                continue
            await try_play_sound(sound)


async def alias_task(mqtt_client, sound, topic, value):
    await mqtt_client.subscribe(topic)
    async with mqtt_client.filtered_messages(topic) as msgs:
        async for msg in msgs:
            if value is not None and value != msg.payload.decode():
                continue
            await try_play_sound(msg.payload.decode())


async def main():
    global config
    config_file = sys.argv[1] if len(sys.argv) > 1 else 'soundboard.yaml'
    config = load_config(config_file)

    logger.setLevel(config.get('loglevel', 'WARNING'))

    mqtt_host = config['mqtt']['host']
    mqtt_client = aiomqtt.Client(mqtt_host)
    await mqtt_client.connect()
    logger.info(f'connected to {mqtt_host}')

    handler_tasks = []

    mqtt_sound_topic = config['sounds']['topic']
    handler_tasks.append(asyncio.create_task(main_task(mqtt_client, mqtt_sound_topic)))
    logger.info(f'main sounds topic is {mqtt_sound_topic}')

    for alias in config.get('aliases', None) or []:
        sound, topic, value = alias['sound'], alias['topic'], alias.get('value', '*')
        handler_tasks.append(asyncio.create_task(alias_task(mqtt_client, sound, topic, value)))
        logger.info(f'added alias {topic} == {value}')

    await asyncio.gather(*handler_tasks)


if __name__ == '__main__':
    asyncio.run(main())
