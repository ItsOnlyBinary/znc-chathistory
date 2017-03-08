# znc-chathistory
Implements the `CHATHISTORY` command, enabling infinite chathistory in clients by pulling previous content from log files and sending them to the client as raw IRC lines.

## Table of Contents
- [Requirements](#requirements)
- [Installation](#installation)
- [Loading](#loading)
- [Commands](#commands)
- [Command Specification](#developer-information)
- [Contributors](#contributors)
- [Contact](#contact)
- [License](#license)

## Requirements
 - <a href="http://znc.in">ZNC 1.6 or later</a>
     - Log files named per the [ZNC 1.6 log module](http://wiki.znc.in/Log#Arguments)  (`%Y-%m-%d.log`)
 - <a href="https://www.python.org">Python 3</a>
 - <a href="http://wiki.znc.in/Modpython">modpython</a>
 - **Your client must have support for the `CHATHISTORY` command as outlined in the [Developer Information](#developer-information). Speak with your client developer if you would like this feature supported.**

## Installation
To install *znc-chathistory*, place `chathistory.py` in your ZNC modules folder

## Loading
`/znc loadmod chathistory`

## Commands

`set <option> <value>` Set the [configuration options](#settings)

`settings` Display your current settings

`about` Display information about this module

`help` Print help for this module

### Configuration Options

`size` **integer** The amount of lines to retrieve during each chathistory request. This is he max amount of lines a client will be allowed to request.

`extras` **True/False**  Include extra events in chathistory (join, kick, mode, nick, quit, part, topic)

`strip` **True/False** Strip control codes from output

`path` **path_to_file** 
Specify the complete, absolute path to your log files. Accepted variables (case sensitive):
- Current user: `$USER`
- Current network: `$NETWORK`
- Channel / query: `$WINDOW`

`debug` **True/False** Send output to module instead of client

## Developer Information
Please see the [IRCv3 draft specification](https://github.com/ircv3/ircv3-specifications/pull/292) for information on implemention and supporting this batch type.

Due to limitations with ZNC 1.6 and the log format, `draft/label` and `draft/msgid` are not supported. The command SHOULD be sent without a `draft/label` and content is returned without a `draft/msgid`. If a `draft/label` is prefixed to the `CHATHISTORY` command, ZNC will ignore it.

## Contributors
Special thank you to [DanielOaks](https://github.com/DanielOaks) and [prawnsalad](https://github.com/prawnsalad) for providing IRCv3 support and feedback.

## Contact
Issues/bugs should be submitted on the <a href="https://github.com/MuffinMedic/znc-chathistory/issues">GitHub issues page</a>.

For assistance, please PM MuffinMedic (Evan) on <a href="https://kiwiirc.com/client/irc.snoonet.org:+6697">Snoonet</a> or <a href="https://kiwiirc.com/client/irc.freenode.net:+6697">freenode<a/>.

## License
This software is copyright Evan Magaliff and licensed under the GPLv3 license. See the [LICENSE](https://github.com/MuffinMedic/znc-chathistory/blob/master/LICENSE) for more information.