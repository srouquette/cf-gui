#!/usr/bin/env python
# encoding: utf-8
# author: sylvain rouquette

from colorama.ansi import clear_screen
import colorama
from datetime import datetime, timedelta
import json
import os
import re
import subprocess
import sys
import time


COMMANDS = {
    'logs': 'cf logs {name}',
    'logs recent': 'cf logs --recent {name}',
    'push': 'cf push {name} -d {domain}',
    'restart': 'cf restart {name}',
    'target': 'cf target -s {name}',
    'refresh': 'refresh',
}

def _find_getch():
    try:
        import termios
    except ImportError:
        # Non-POSIX. Return msvcrt's (Windows') getch.
        import msvcrt
        return msvcrt.getch
    # POSIX system. Create and return a getch that manipulates the tty.
    import sys, tty, select
    def setup_term(fd, when=termios.TCSAFLUSH):
        mode = termios.tcgetattr(fd)
        mode[tty.LFLAG] = mode[tty.LFLAG] & ~(termios.ECHO | termios.ICANON)
        termios.tcsetattr(fd, when, mode)
    def _getch():
        fd = sys.stdin.fileno()
        old_settings = termios.tcgetattr(fd)
        try:
            setup_term(fd)
            try:
                rw, wl, xl = select.select([fd], [], [])
            except select.error:
                return
            if rw:
                readch = lambda nb: bytes(sys.stdin.read(nb), 'utf-8')
                ch = readch(1)
                if ch != b'\x1b':
                    return ch
                else:
                    return readch(2)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
    return _getch
getch = _find_getch()


class CommandExecutor:
    def execute(self, command):
        print(command)
        if sys.platform == 'win32':
            with open('cf-command.bat', 'wt') as f:
                f.write(command)
        else:
            with open('cf-command.sh', 'wt') as f:
                command = ['#!/usr/bin/env bash', command]
                f.write('\n'.join(command))
        if 'target' in command:
            subprocess.Popen(['cf', command[3:]])

    def target(self):
        return '''
Cloud Foundry
Login: my_email@gmail.com
Space: JaegerInt
Domain: jaeger.int.domain.com
'''.splitlines()

    def spaces(self):
        return '''
JaegerInt
ImagingDev
'''.splitlines()

    def services(self):
        return '''
Getting apps in org domain.com/ space JaegerInt as syl...
OK

name                         requested state   instances   memory   disk   urls
group_builder                started           ?/1         512M     1G     group_builder.jaeger.int.domain.com
volume_controller            started           ?/1         384M     1G     volume_controller.jaeger.int.domain.com
mpr_rendering                started           1/1         384M     1G     mpr_rendering.jaeger.int.domain.com
'''.splitlines()


class CfCommandExecutor(CommandExecutor):
    def target(self):
        return subprocess.Popen(['cf', 'target'], stdout=subprocess.PIPE)
    def spaces(self):
        return subprocess.Popen(['cf', 'spaces'], stdout=subprocess.PIPE)
    def services(self):
        return subprocess.Popen(['cf', 'apps'], stdout=subprocess.PIPE)


class Settings:
    FILE = os.path.sep.join((os.path.expanduser('~'), 'cf-gui.json'))
    TIME_FORMAT = '%Y-%m-%d %H:%M'
    PATTERNS = {
        'user'   : re.compile(r'^Login.*\s+(.*)\s?'),
        'space'  : re.compile(r'^Space.*\s+(.*)\s?'),
        'domain' : re.compile(r'^Domain.*\s+(.*)\s?'),
        'check_space': re.compile(r'^Getting.*space\s+([^\s]+)\s+'),
        'service': re.compile(r'^([^\s]+)(\s+\w+\s+)(.{3})(\s+[^\s]+\s+[^\s]+\s+)([^\s]+)')  # (name)(ignore)(status)(ignore)(routes)
    }

    def __init__(self, executor):
        self.json = {}
        try:
            with open(Settings.FILE) as f:
                self.json = json.load(f)
        except:
            pass
        self.check(executor)

    @property
    def space_name(self):
        return self.json['target']['space']

    @space_name.setter
    def space_name(self, value):
        self.json['target']['space'] = value

    @property
    def space(self):
        return self.json['spaces'][self.space_name]

    @property
    def spaces(self):
        return [{ 'name': key } for key in self.json['spaces'].keys()]

    @property
    def services(self):
        return [dict(domain = self.space['domain'], **service) for service in self.space['services']]

    def check(self, executor):
        if not 'target' in self.json:
            print('updating target...')
            self.update_target(executor.target())
        if not 'spaces' in self.json:
            print('updating spaces...')
            self.update_spaces(executor.spaces())
        if not 'services' in self.space or not self.check_space_timestamp():
            print('updating space %s...' % self.space_name)
            self.update_space(executor.services())

    def check_space_timestamp(self):
        if not 'timestamp' in self.space:
            return False
        if datetime.now() - datetime.strptime(self.space['timestamp'], Settings.TIME_FORMAT) > timedelta(days=1):
            return False
        return True

    def save(self):
        with open(Settings.FILE, 'wt') as f:
            json.dump(self.json, f)

    def update_target(self, lines):
        result = {}
        def match_and_update(key, line):
            m = Settings.PATTERNS[key].match(line)
            if m:
                result[key] = m.group(1)
        target_info = ('user', 'space', 'domain')
        for line in lines:
            for key in target_info:
                if not key in result:
                    match_and_update(key, line)
        if 'target' in self.json:
            self.json['target'] = dict(self.json['target'], **result)
        else:
            self.json['target'] = result

    def update_spaces(self, lines):
        if not 'spaces' in self.json:
            self.json['spaces'] = {}
        for line in lines:
            if line.strip() and not line in self.json['spaces']:
                self.json['spaces'][line] = {}

    def update_space(self, lines):
        for line in lines:
            m = Settings.PATTERNS['check_space'].match(line)
            if m and self.space_name != m.group(1):
                raise Exception("target doesn't match current space: %s != %s" % (self.space_name, m.group(1)))
        services_definition = False
        services = []
        self.space['domain'] = self.json['target']['domain']
        for line in lines:
            if not services_definition:
                if line.startswith('name'):
                    services_definition = True
                continue
            m = Settings.PATTERNS['service'].match(line)
            if not m:
                continue
            services.append({
                'name': m.group(1),
                'status': m.group(3),
                'routes': m.group(5)
            })
        self.space['services'] = services
        self.space['timestamp'] = str(datetime.now().strftime(Settings.TIME_FORMAT))


class Menu:
    def __init__(self, listener, items, command):
        self.listener = listener
        self.current = 0
        self.items = sorted(items, key = lambda item: item['name'])
        self.command = command

    def next(self):
        self.current = (self.current + 1) % len(self.items)

    def prev(self):
        self.current = (self.current - 1) % len(self.items)

    def select(self, index):
        self.current = index

    def __str__(self):
        result = []
        for i, item in enumerate(self.items):
            start = '> ' if i == self.current else '  '
            if not 'status' in item:
                color = colorama.Fore.RESET
            elif item['status'].startswith('0/'):
                color = colorama.Fore.RED
            elif item['status'].startswith('?/'):
                color = colorama.Fore.MAGENTA
            else:
                color = colorama.Fore.RESET
            result.append('%s%s %d %s' % (color, start, i, item['name']))
        return '\n'.join(result)

    def activate(self):
        self.listener.execute_command(self.command, self.items[self.current])
        return True


class MenuMain(Menu):
    def __init__(self, listener, items):
        super().__init__(listener, items, None)

    def activate(self):
        return self.listener.execute_main(self.items[self.current]['command'])


class MenuFactory:
    def __init__(self):
        pass

    def create(self, listener, items, command):
        if command == 'main':
            return MenuMain(listener, items)
        else:
            return Menu(listener, items, command)


class App:
    def __init__(self, settings, menu_factory, executor):
        self.settings = settings
        self.menu_factory = menu_factory
        self.executor = executor
        reformatted_commands = [{ 'name': key, 'command': value } for key, value in COMMANDS.items()]
        self.menu = self.menu_factory.create(self, reformatted_commands, 'main')

    def execute_command(self, command, args):
        if 'target' in command:
            self.settings.space_name = args['name']
        self.executor.execute(command.format(**args))

    def execute_main(self, command):
        if 'refresh' in command:
            del self.settings.space['timestamp']
            return True
        elif 'target' in command:
            self.menu = self.menu_factory.create(self, settings.spaces, command)
        else:
            self.menu = self.menu_factory.create(self, settings.services, command)
        return False

    def run(self):
        WIN32 = sys.platform == 'win32'
        decode_key = lambda key: key if type(key) == int else int.from_bytes(key.encode(), byteorder='big')
        while True:
            print(clear_screen())
            print(self.menu)
            key = getch()
            if WIN32 and key == b'\xe0':
                arrow = getch()
                if arrow == b'H':    # up
                    self.menu.prev()
                elif arrow == b'P':  # down
                    self.menu.next()
            elif not WIN32 and len(key) > 1:
                if key == b'[A':    # up
                    self.menu.prev()
                elif key == b'[B':  # down
                    self.menu.next()
            elif key == b'\r' or key == b'\n':
                if self.menu.activate():
                    break
            elif key >= b'0' and key <= b'9':
                self.menu.select(key[0] - ord('0'))
                if self.menu.activate():
                    break
            elif key == b'\x1b' or key == b'\x03' or key == b'q':
                break


if __name__ == '__main__':
    colorama.init()
    executor = CommandExecutor()
    settings = Settings(executor)
    app = App(settings, MenuFactory(), executor)
    app.run()
    settings.save()
