import json
import os.path
import random, string
import re
import znc
from collections import defaultdict

VERSION = '1.0.2'
UPDATED = "December 8, 2016"

COMMAND = "SCROLLBACK"
BATCH_ID_SIZE = 13

# Default user configuration if they haven't set a value themselves
DEFAULT_CONFIG = defaultdict(dict)
DEFAULT_CONFIG['size'] = 50
DEFAULT_CONFIG['extras'] = False
DEFAULT_CONFIG['path'] = znc.CZNC.Get().GetZNCPath() + '/users/$USER/moddata/log/$NETWORK/$WINDOW/'
DEFAULT_CONFIG['strip'] = False
DEFAULT_CONFIG['debug'] = False

# The default 'ident' and 'host' values to be used if they are not contained in the log
DEFAULT_IDENT = 'scrollback'
DEFAULT_HOST = 'znc.in'

# Regex patterns needed to extract the IRC events out of the logs
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

class scrollback(znc.Module):

    module_types = [znc.CModInfo.GlobalModule]
    description = "ZNC scrollback support"
    wiki_page = "Scrollback"

    # Glbal configuration containing all users who changed their settings
    config = defaultdict(dict)

    def OnLoad(self, args, message):
        config_file = self.GetSavePath() + '/' + 'scrollback.json'
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
                    self.send_isupport(client)
        return True

    def OnClientLogin(self):
        client = self.GetClient()
        self.send_isupport(client)

    def OnUserRaw(self, line):
        line = str(line).split()
        # Handle the scrollback command send by the client
        if line[0].upper() == COMMAND:
            user = self.GetUser().GetUserName()
            network = self.GetNetwork().GetName()
            target = line[1].lower()

            user_config = self.get_user_config()
            user_config['path'] = user_config['path'].replace('$USER', user).replace('$NETWORK', network).replace('$WINDOW', target)

            # SCROLLBACK target start_date start_time
            # SCROLLBACK #mutterirc 2016-11-12 13:10:01
            self.parse_logs(user_config, network, target, line[2], line[3])
            return znc.HALT
        elif line[0]== "VERSION":
            client = self.GetClient()
            self.send_isupport(client)

    def send_isupport(self, client):
        client.PutClient(':irc.znc.in 005 {} {} :are supported by this server'.format(client.GetNick(), COMMAND))

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

    # Convert and return the raw scrollback from logs to an IRCv3 BATCH
    def generate_batch(self, scrollback, target):
        # Generate a random alphanumeric BATCH ID
        id = ''.join(random.choice(string.ascii_lowercase + string.ascii_uppercase + string.digits) for i in range(BATCH_ID_SIZE))
        # Place the BATCH start identifer to the beginning of the scrollback
        line = ':znc.in BATCH +{} scrollback {}'.format(id, target)
        self.send_scrollback(line)
        # Prepend the BATCH ID to each line from the scrollback
        for line in scrollback:
            line = '@batch={};{}'.format(id, line)
            self.send_scrollback(line)
        # Place the BATCH end identifer to the beginning of the scrollback
        line = ':znc.in BATCH -{}'.format(id)
        self.send_scrollback(line)

    # Send the given line to the user
    def send_scrollback(self, line):
        user_config = self.get_user_config()
        if user_config['debug']:
            self.PutModule(line)
        else:
            self.GetClient().PutClient(line)

    # Parse through the log files, extract the appropritae content, format a raw IRC line, and send the line for BATCH processing
    def parse_logs(self, user_config, network, target, start_date, start_time):
        scrollback = []
        isFirstFile = True
        path = user_config['path']
        # Get a list of all log files in the given user, network, and window
        files = sorted([f for f in os.listdir(path) if log_file_name_regex.match(f) and f.split('.')[0] <= start_date], reverse=True)
        # Iterate through each file in reverse order, checking if the max number of lines has been reached
        for file in files:
            if len(scrollback) <= user_config['size']:
                for line in reversed(list(open(path + file, 'r'))):
                    if len(scrollback) <= user_config['size']:
                        # Strip control codes if set by user
                        if user_config['strip']:
                            line = strip_control_codes_regex.sub('', line)
                        split_line = line.split()
                        # Check if the current line is before the given date and time by the client
                        if ((split_line[0]).replace('[', '') < start_time and isFirstFile) or not isFirstFile:
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
                                    scrollback.insert(0, line)

                                elif notice_regex.match(line):
                                    action = 'NOTICE'
                                    nick = self.get_nick_string(split_line[1], action)
                                    message = self.get_message_string(split_line[2:], action)

                                    line = '{} :{}!{}@{} NOTICE {} :{}'.format(time, nick, DEFAULT_IDENT, DEFAULT_HOST, target, message)
                                    scrollback.insert(0, line)

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

                                            scrollback.insert(0, line)

                                        elif kicked_regex.match(line):
                                            action = 'KICK'
                                            kicked_nick = self.get_nick_string(split_line[2], action)
                                            op_nick = self.get_nick_string(split_line[6], action)
                                            reason = self.get_message_string(split_line[7:], action)

                                            line = '{} :{}!{}@{} KICK {} {} :{}'.format(time, op_nick, DEFAULT_IDENT, DEFAULT_HOST, target, kicked_nick, reason)
                                            scrollback.insert(0, line)

                                        elif new_nick_regex.match(line):
                                            action = 'NICK'
                                            old_nick = self.get_nick_string(split_line[2], action)
                                            new_nick = self.get_nick_string(split_line[7], action)

                                            line = '{} :{}!{}@{} NICK :{}'.format(time, old_nick, DEFAULT_IDENT, DEFAULT_HOST, new_nick)
                                            scrollback.insert(0, line)

                                        elif topic_change_regex.match(line):
                                            action = 'TOPIC'
                                            nick = self.get_nick_string(split_line[2], action)
                                            topic = self.get_message_string(split_line[6:], action)

                                            line = '{} :{}!{}@{} TOPIC {} :{}'.format(time, nick, DEFAULT_IDENT, DEFAULT_HOST, target, topic)
                                            scrollback.insert(0, line)

                                        elif mode_change_regex.match(line):
                                            action = 'MODE'
                                            nick = self.get_nick_string(split_line[2], action)
                                            modes = self.get_message_string(split_line[5:], action)

                                            line = '{} :{}!{}@{} MODE {} {}'.format(time, nick, DEFAULT_IDENT, DEFAULT_HOST, target, modes)
                                            scrollback.insert(0, line)
                    else:
                        break
            else:
                break

            isFirstFile = False

        # Send the parsed scrollback to be formatted as an IRCv3 BATCH
        self.generate_batch(scrollback, target)

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
        config_file = self.GetSavePath() + '/' + 'scrollback.json'
        user = self.GetUser().GetUserName()
        self.config[user][key] = value

        with open(config_file, 'w') as data_file:
            json.dump(self.config, data_file, indent=4, sort_keys=True)

        self.PutModule("\x02Settings updated.\x02")

    def about(self):
        self.PutModule("\x02scollback\x02 ZNC module by MuffinMedic (Evan)")
        self.PutModule("\x02Description:\x02 {}".format(self.description))
        self.PutModule("\x02Version:\x02 {}".format(VERSION))
        self.PutModule("\x02Updated:\x02 {}".format(UPDATED))
        self.PutModule("\x02Documentation and Source:\x02 https://github.com/MuffinMedic/znc-scrollback")

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
                        self.set_config(setting_name, setting_value)
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