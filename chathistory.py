#  znc-chathistory: ZNC chathistory support
#  Copyright (C) 2017 Evan Magaliff
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #
#  Authors: Evan (MuffinMedic)                                            #
#  Contributors: doaks, kr0n, prawnsalad                                  #
#  Desc: Implements the IRCv3 CHATHISTORY extension to allow clients to   #
#        request historical content from ZNC for inline playback.         #
# # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # # #

import json
import os.path
import random, string
import re
import uuid
import znc
from collections import defaultdict

VERSION = '1.0.5'
UPDATED = "March 7, 2017"

COMMAND = "CHATHISTORY"
BATCH_ID_SIZE = 13

# Default user configuration if they haven't set a value themselves
DEFAULT_CONFIG = defaultdict(dict)
DEFAULT_CONFIG['size'] = 50
DEFAULT_CONFIG['extras'] = False
DEFAULT_CONFIG['path'] = znc.CZNC.Get().GetZNCPath() + '/users/$USER/moddata/log/$NETWORK/$WINDOW/'
DEFAULT_CONFIG['strip'] = False
DEFAULT_CONFIG['debug'] = False

# The default 'ident' and 'host' values to be used if they are not contained in the log
DEFAULT_IDENT = 'chathistory'
DEFAULT_HOST = 'znc.in'

# Regex patterns needed to extract the IRC events out of the logs
#command_regex = re.compile(r'^(@label=[A-Z0-9_\-]+ :CHATHISTORY (#|&|!|\+).* [0-9]{4}-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]\.[0-9]{3}Z [0-9|\*]+)$', re.IGNORECASE)
command_regex = re.compile(r'^(CHATHISTORY \S+ [0-9]{4}-[0-1][0-9]-[0-3][0-9]T[0-2][0-9]:[0-5][0-9]:[0-5][0-9]\.[0-9]{3}Z -?[0-9|\*]+)$', re.IGNORECASE)
log_file_name_regex = re.compile(r'^\d{4}-\d{2}-\d{2}\.log')
timestamp_regex = re.compile(r'^\[([\d:]+)\]')
privmsg_regex = re.compile(r'^\[([\d:]+)\] <')
notice_regex = re.compile(r'^\[([\d:]+)\]\ -(.*)\-\ (.*)')
action_regex = re.compile(r'^\[([\d:]+)\] \*\*\*')
kicked_regex = re.compile(r'^\[([\d:]+)\] \*\*\*\ (.*)\ was\ kicked\ by\ (.*)\ \((.*)\)')
new_nick_regex = re.compile(r'^\[([\d:]+)\] \*\*\*\ (.*)\ is now known as (.*)')
topic_change_regex = re.compile(r'^\[([\d:]+)\] \*\*\*\ (.*)\ changes\ topic\ to\ (.*)')
mode_change_regex = re.compile(r'^\[([\d:]+)\] \*\*\*\ (.*)\ sets mode: (.*)')

# Regex to remove any control codes from the output
strip_control_codes_regex = re.compile("\x1d|\x1f|\x0f|\x02|\x03(?:\d{1,2}(?:,\d{1,2})?)?", re.UNICODE)

class chathistory(znc.Module):

    module_types = [znc.CModInfo.GlobalModule]
    description = "ZNC chathistory support"
    wiki_page = "Chathistory"

    # Glbal configuration containing all users who changed their settings
    config = defaultdict(dict)

    def OnLoad(self, args, message):
        config_file = self.GetSavePath() + '/' + 'chathistory.json'
        if os.path.exists(config_file):
            with open(config_file) as data_file:
                self.config = json.load(data_file)

        usermap = znc.CZNC.Get().GetUserMap()
        for user in usermap.items():
            networks = user[1].GetNetworks()
            for network in networks:
                clients = network.GetClients()
                for client in clients:
                    nick = client.GetNick()
                    self.send_isupport(client, False)
        return True

    def OnClientLogin(self):
        client = self.GetClient()
        self.send_isupport(client, True)

    def OnUserRaw(self, line):
        line_split = str(line).split()
        client = self.GetClient()
        user_config = self.get_user_config()
        max_message_count = user_config['size']
        # Handle the chathistory command send by the client
        if line_split[0].upper() == COMMAND:
            if command_regex.match(str(line)):
                user = self.GetUser().GetUserName()
                network = self.GetNetwork().GetName()
                target = line_split[1].lower()

                user_config = self.get_user_config()
                user_config['path'] = user_config['path'].replace('$USER', user).replace('$NETWORK', network).replace('$WINDOW', target)

                # CHATHISTORY target start_date start_time message_count
                # CHATHISTORY #mutterirc 2016-11-12T13:10:01.000Z 100
                start_date = (line_split[2].split('T')[0]).replace('timestamp=', '')
                start_time = (line_split[2].split('T')[1]).split('.')[0]
                if line_split[3] == '*':
                        message_count = user_config['size']
                else:
                    message_count = float(line_split[3])
                if line_split[3] == '*':
                    message_count = user_config['size']
                if message_count != 0:
                    try:
                        if abs(message_count) > max_message_count:
                            self.send_error(client, 'WARN', 'MAX_MESSAGE_COUNT_EXCEEDED')
                            message_count = max_message_count if message_count > 0 else max_message_count * -1
                        self.parse_logs(user_config, network, target, start_date, start_time, message_count)
                        return znc.HALT
                    except:
                        pass
                else:
                    self.send_error(client, 'ERR', 'MSG_COUNT_INVALID')
            else:
                self.send_error(client, 'ERR', 'CMD_INVALID')

        elif line_split[0].upper() == "VERSION":
            self.send_isupport(client, True)

    def send_isupport(self, client, user_exists):
        if user_exists:
            config = self.get_user_config()
            size = user_config['size']
        else:
            try:
                size = self.GetUser().GetBufferCount()
            except:
                size = znc.CZNC.Get().GetMaxBufferSize()
        client.PutClient(':irc.znc.in 005 {} {}={} :are supported by this server'.format(client.GetNick(), COMMAND, size))

    def send_error(self, client, type, error):
        user_config = self.get_user_config()
        if user_config['debug']:
            self.PutModule("{} CHATHISTORY {} :{}".format(client.GetNickMask(), type, error))
        else:
            client.PutClient("{} CHATHISTORY {} :{}".format(client.GetNickMask(), type, error))
            
    # Format and return the 'time=YYYY-mm-ddTHH:mm:ss.000Z' string to be prepended to the IRC line
    def get_time_string(self, time, file):
        time = time.replace('[', 'time=' + file.split('.')[0] + 'T', 1)
        time = time.replace(']', '.000Z', 1)
        return time

    # Format and return the raw nick from the given line split
    def get_nick_string(self, nick, action):
        if action == 'PRIVMSG':
            nick = re.search(r'\<(.*?)\>', nick)
            nick = re.sub(r'\<|\>', '', nick.group(0))
        elif action == 'NOTICE':
            nick = nick.strip('-')
        else:
            nick = nick
        return nick

    # Format and return the raw ident from the given line split
    def get_ident_string(self, ident, action):
        if action == 'PRIVMSG':
            ident = DEFAULT_IDENT
        else:
            ident = (ident.split('@')[0]).strip('(')
        return ident

    # Format and return the raw host from the given line split
    def get_host_string(self, host, action):
        if action == 'PRIVMSG':
            host = DEFAULT_HOST
        else:
            host = (host.split('@')[1]).strip(')')
        return host

    # Format and return the raw message from the given line split
    def get_message_string(self, message, action):
        if action == 'PRIVMSG' or action == 'MODE' or action == 'NOTICE':
             message = ' '.join(message)
        elif action == 'KICK':
            message = ' '.join(message).strip('(').strip(')')
        elif action == 'TOPIC':
            message = ' '.join(message).strip('\'').strip('\'')
        else:
            message = None
        return message

    # Convert and return the raw chathistory from logs to an IRCv3 BATCH
    def generate_batch(self, chathistory, target):
        if len(chathistory) > 0:
            # Generate a random alphanumeric BATCH ID
            batch_id = ''.join(random.choice(string.ascii_lowercase + string.ascii_uppercase + string.digits) for i in range(BATCH_ID_SIZE))
            # Place the BATCH start identifer to the beginning of the chathistory
            line = 'irc.znc.in BATCH +{} chathistory {}'.format(batch_id, target)
            self.send_chathistory(line)
            # Prepend the BATCH ID to each line from the chathistory
            for line in chathistory:
                msg_id = uuid.uuid4()
                line = '@batch={};draft/msgid={};{}'.format(batch_id, msg_id, line)
                self.send_chathistory(line)
            # Place the BATCH end identifer to the beginning of the chathistory
            line = 'irc.znc.in BATCH -{}'.format(batch_id)
            self.send_chathistory(line)
        else:
            client = self.GetClient()
            self.send_error(client, 'ERR', 'NOT_FOUND')

    # Send the given line to the user
    def send_chathistory(self, line):
        user_config = self.get_user_config()
        if user_config['debug']:
            self.PutModule(line)
        else:
            self.GetClient().PutClient(line)

    # Parse through the log files, extract the appropritae content, format a raw IRC line, and send the line for BATCH processing
    def parse_logs(self, user_config, network, target, start_date, start_time, message_count):
        chathistory = []
        isFirstFile = True
        path = user_config['path']
        # Get a list of all log files in the given user, network, and window
        files = sorted([f for f in os.listdir(path) if log_file_name_regex.match(f) and f.split('.')[0] <= start_date], reverse=True)
        # Iterate through each file in reverse order, checking if the max number of lines has been reached
        for file in files:
            if len(chathistory) < abs(message_count):
                lines = list(open(path + file, 'r'))
                if message_count < 0:
                    lines = reversed(lines)
                for line in lines:
                    if len(chathistory) < abs(message_count):
                        # Strip control codes if set by user
                        if user_config['strip']:
                            line = strip_control_codes_regex.sub('', line)
                        split_line = line.split()
                        # Check if the current line is before the given date and time by the client
                        if message_count > 0:
                            if ((split_line[0]).replace('[', '') > start_time and isFirstFile) or not isFirstFile:
                                line = self.format_line(line, target, file)
                                chathistory.insert(0, line)
                        elif message_count < 0:
                            if ((split_line[0]).replace('[', '') < start_time and isFirstFile) or not isFirstFile:
                                line = self.format_line(line, target, file)
                                chathistory.insert(0, line)
                    else:
                        break
            else:
                break

            isFirstFile = False

        # Send the parsed chathistory to be formatted as an IRCv3 BATCH
        if message_count > 0:
            chathistory.reverse()
        self.generate_batch(chathistory, target)

    def format_line(self, line, target, file):
        split_line = line.split()
        # Handle each line and parse various events
        if timestamp_regex.match(line):
            time = self.get_time_string(split_line[0], file)

            if privmsg_regex.match(line):
                action = 'PRIVMSG'
                nick = self.get_nick_string(split_line[1], action)
                ident = self.get_ident_string(None, action)
                host = self.get_host_string(None, action)
                message = self.get_message_string(split_line[2:], action)
                
                line = '{} :{}!{}@{} PRIVMSG {} :{}'.format(time, nick, DEFAULT_IDENT, DEFAULT_HOST, target, message)

            elif notice_regex.match(line):
                action = 'NOTICE'
                nick = self.get_nick_string(split_line[1], action)
                message = self.get_message_string(split_line[2:], action)

                line = '{} :{}!{}@{} NOTICE {} :{}'.format(time, nick, DEFAULT_IDENT, DEFAULT_HOST, target, message)

            # Parse 'extra' events if set by user
            elif user_config['extras']:
                if action_regex.match(line):
                    action = (split_line[2]).strip('s:').upper()
                    message = self.get_message_string(None, False)

                    if action == 'JOIN' or action == 'PART' or action == 'QUIT':
                        nick = self.get_nick_string(split_line[3], action)
                        ident = self.get_ident_string(split_line[4], action)
                        host = self.get_host_string(split_line[4], action)

                        if action == 'JOIN':
                            line = '{} :{}!{}@{} {} :{}'.format(time, nick, ident, host, action, target).strip()
                        elif action == 'PART' or action == 'QUIT':
                            message = ' '.join(split_line[5:]).strip('(').strip(')')
                            line = '{} :{}!{}@{} {} {} :{}'.format(time, nick, ident, host, action, target, message).strip()

                    elif kicked_regex.match(line):
                        action = 'KICK'
                        kicked_nick = self.get_nick_string(split_line[2], action)
                        op_nick = self.get_nick_string(split_line[6], action)
                        reason = self.get_message_string(split_line[7:], action)

                        line = '{} :{}!{}@{} KICK {} {} :{}'.format(time, op_nick, DEFAULT_IDENT, DEFAULT_HOST, target, kicked_nick, reason)

                    elif new_nick_regex.match(line):
                        action = 'NICK'
                        old_nick = self.get_nick_string(split_line[2], action)
                        new_nick = self.get_nick_string(split_line[7], action)

                        line = '{} :{}!{}@{} NICK :{}'.format(time, old_nick, DEFAULT_IDENT, DEFAULT_HOST, new_nick)

                    elif topic_change_regex.match(line):
                        action = 'TOPIC'
                        nick = self.get_nick_string(split_line[2], action)
                        topic = self.get_message_string(split_line[6:], action)

                        line = '{} :{}!{}@{} TOPIC {} :{}'.format(time, nick, DEFAULT_IDENT, DEFAULT_HOST, target, topic)

                    elif mode_change_regex.match(line):
                        action = 'MODE'
                        nick = self.get_nick_string(split_line[2], action)
                        modes = self.get_message_string(split_line[5:], action)

                        line = '{} :{}!{}@{} MODE {} {}'.format(time, nick, DEFAULT_IDENT, DEFAULT_HOST, target, modes)
            return line

    # Get the configuraton of the current user, returning default value if not explicitly set by uesr
    def get_user_config(self):
        user = self.GetUser().GetUserName()
        user_config = defaultdict(dict)
        for key, value in DEFAULT_CONFIG.items():
            try:
                user_config[key] = self.config[user][key]
            except KeyError:
                user_config[key] = value
        return user_config

    # Set the configuration option for the current user as sent to the module and then write it to the config file
    def set_config(self, key, value):
        config_file = self.GetSavePath() + '/' + 'chathistory.json'
        user = self.GetUser().GetUserName()
        self.config[user][key] = value

        with open(config_file, 'w') as data_file:
            json.dump(self.config, data_file, indent=4, sort_keys=True)

        self.PutModule("\x02Settings updated.\x02")

    def about(self):
        self.PutModule("\x02scollback\x02 ZNC module by MuffinMedic (Evan)")
        self.PutModule("\x02Contributors:\x02 doaks, kr0n, prawnsalad")
        self.PutModule("\x02Description:\x02 {}".format(self.description))
        self.PutModule("\x02Version:\x02 {}".format(VERSION))
        self.PutModule("\x02Updated:\x02 {}".format(UPDATED))
        self.PutModule("\x02Documentation and Source:\x02 https://github.com/MuffinMedic/znc-chathistory")

    # Handle each of the user commands
    def OnModCommand(self, command):
        # List of valid commands
        cmds = ["set", "settings", "help", "about"]
        split_cmd = command.split()
        lower_split_cmd = (command.lower()).split()
        if lower_split_cmd[0] in cmds:
            try:
                if lower_split_cmd[0] == "set":
                    setting_name = lower_split_cmd[1]
                    setting_value = lower_split_cmd[2]
                    if setting_name == "size":
                        try:
                            if int(setting_value) > 0:
                                self.set_config(setting_name, int(setting_value))
                            else:
                                raise ValueError
                        except ValueError:
                            self.PutModule("You must enter a positive integer value.")
                    elif setting_name == 'extras' or setting_name == 'strip' or setting_name == 'debug':
                        if setting_value.lower() == "true" or setting_value.lower() == "false":
                            if setting_value.lower() == "true":
                                self.set_config(setting_name, True)
                            elif setting_value.lower() == "false":
                                self.set_config(setting_name, False)
                        else:
                            self.PutModule("You must enter True or False.")
                    elif setting_name == "path":
                        self.set_config(setting_name, split_cmd[2])
                    else:
                        self.PutModule("Invalid setting. See \x02help.\x02")
                elif lower_split_cmd[0] == "settings":
                    user_config = self.get_user_config()
                    for key, value in user_config.items():
                        self.PutModule('\x02{}\x02: {}'.format(key.title(), value))
                elif lower_split_cmd[0] == "help":
                    self.help()
                elif lower_split_cmd[0] == "about":
                    self.about()
            except IndexError:
                self.PutModule("Invalid number of arguments. See \x02help\x02.")
        else:
            self.PutModule("Invalid command. See \x02help\x02 for a list of available commands.")
   
   # Generate and output a table of commands, arguments, and their descriptions
    def help(self):
        help = znc.CTable(250)
        help.AddColumn("Command")
        help.AddColumn("Arguments")
        help.AddColumn("Description")
        help.AddRow()
        help.SetCell("Command", "set")
        help.SetCell("Arguments", "<setting> <variable>")
        help.SetCell("Description", "Set the configuration options. See README for more information.")
        help.AddRow()
        help.SetCell("Command", "settings")
        help.SetCell("Arguments", "")
        help.SetCell("Description", "Display your current settings.")
        help.AddRow()
        help.SetCell("Command", "about")
        help.SetCell("Description", "Display information about this module")
        help.AddRow()
        help.SetCell("Command", "help")
        help.SetCell("Arguments", "")
        help.SetCell("Description", "Display this table.")

        self.PutModule(help)