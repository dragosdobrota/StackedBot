import json
import os
import pathlib
import shelve

# Datetime calculations
from datetime import datetime, timedelta, timezone
from functools import partial

# Support for notifications
import aiocron
import discord
import flag
import inspirobot
import requests

# Wikipedia lookups
import wikipedia

# Chat bot
from chatterbot import ChatBot, languages
from chatterbot.trainers import ListTrainer

# Load environment
from dotenv import load_dotenv

# Translation support
from googletrans import Translator

# Google sheet integration
# from apiclient import discovery
# from google.oauth2 import service_account
# SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
# SPREAD_SHEET='1ksHbbJGGaPI4ytMUeXfNmy33ejuw3YznP4XDor1GaMA'

from enum import Enum
class Region(Enum):
    EU = 1
    NA = 2

load_dotenv()

# Fixing spacy at runtime, it is required to previously call 'python -m spacy download en'
languages.ENG.ISO_639_1 = "en_core_web_sm"

URBAN_DICTIONARY_API_KEY = os.getenv("URBAN_DICTIONARY_API_KEY")
# char limit in Discord when sending a message
DISCORD_CHAR_LIMIT = 2000

# Read codec file for language codes
def readCodeFile(filename):
    with open(filename) as fp:
        line = fp.readline()
        data = {}
        while line:
            if not line.startswith("#"):
                row = line.strip().split("\t")
                data[row[0]] = row[1].replace("{", "").replace("}", "").split(",")
            line = fp.readline()
        return data


# Load plugin
def loadPlugin(plugin_class):
    module_name = "plugins." + plugin_class
    mod = __import__(module_name)
    cls = getattr(mod, plugin_class)
    cls = getattr(cls, plugin_class)
    return cls()


class StackedBot(discord.Client):
    def __init__(self):
        # intents to send messages to users
        intents = discord.Intents.default()
        intents.members = True
        intents.reactions = True
        super().__init__(intents=intents)

        # Roles
        self.com_roles = {
            "eu": None,
            "na": None,
            "everyone": None,
        }

        # Channels
        self.com_channels = {
            "public-eu": None,
            "public-na": None,
            "lobby": None,
        }

        # Persistent state
        self.whatis = shelve.open(os.getenv("WHATISFILE"), writeback=True)
        self.remind_me = shelve.open(os.getenv("REMINDERFILE"), writeback=True)

        # Translator service
        self.translator = Translator()
        self.countryToLanguage = readCodeFile("country_languages.data.in")

        self.initialized = False

        # Work in progress, split stuff out to plugins
        # self.plugins = {}
        # for plugin in os.getenv('PLUGINS').split(" "):
        # 	self.plugins[plugin] = loadPlugin(plugin)

        # Work in progress, Google sheet integration
        # credentials = service_account.Credentials.from_service_account_file('stackedBot.json', scopes=SCOPES)
        # self.sheetService = discovery.build('sheets', 'v4', credentials=credentials)

        # Chatbot
        self.bot = ChatBot(
            "@Stacked",
            storage_adapter="chatterbot.storage.SQLStorageAdapter",
            logic_adapters=[
                "chatterbot.logic.MathematicalEvaluation",
                # 'chatterbot.logic.TimeLogicAdapter',
                "chatterbot.logic.BestMatch",
            ],
            database_uri="sqlite:///database.db",
        )
        self.trainer = ListTrainer(self.bot, show_training_progress=False)
        self.initialize_with_corpus = True

    # Clean message string
    def clean_message(self, message):
        msg = message.clean_content
        try:
            if msg.startswith(">"):
                msg = msg.split("\n")[1]
            if msg.startswith("@"):
                found_user_mention = False
                for member in message.mentions:
                    member_name = (
                        member.nick if member.nick is not None else member.name
                    )
                    if msg.startswith(f"@{member_name}"):
                        msg = msg.replace(f"@{member_name}", "", 1)
                        found_user_mention = True
                if not found_user_mention:
                    msg = msg.split(" ", 1)
                    if len(msg) != 2:
                        return None
                    msg = msg[1]
            if "@" in msg:
                msg = msg.replace("@", "")
        except:
            print(f"Error in parsing message: {message.clean_content}")
            return None
        return msg

    # Prepare the channels and stuff
    async def on_ready(self):
        if self.initialized:
            return

        self.com_roles["eu"] = self.guilds[0].get_role(
            int(os.getenv("EU_ROLE"))
        )
        self.com_roles["na"] = self.guilds[0].get_role(
            int(os.getenv("NA_ROLE"))
        )
        self.com_roles["everyone"] = self.guilds[0].default_role

        self.com_channels["public-eu"] = self.guilds[0].get_channel(
            int(os.getenv("PUBLIC_EU_CHANNEL"))
        )
        self.com_channels["public-na"] = self.guilds[0].get_channel(
            int(os.getenv("PUBLIC_NA_CHANNEL"))
        )
        self.com_channels["lobby"] = self.guilds[0].get_channel(
            int(os.getenv("LOBBY_CHANNEL"))
        )

        for role in self.com_roles:
            if self.com_roles[role] is None:
                print(f"Could not find {role} role")
                quit()

        for channel in self.com_channels:
            if self.com_channels[channel] is None:
                print(f"Could not find {channel} channel")
                quit()

        # Regions
        self.region_configs = {
            Region.EU: {
                "channelId": "public-eu",
                "tz": 1,
                "role": self.com_roles["eu"]
            }, 
            Region.NA: {
                "channelId": "public-na",
                "tz": -6,
                "role": self.com_roles["na"]
            },
        }

        print(f"{self.user.name} has connected to {self.guilds}!")

        # Setup notifications
        self.setup_notifications(Region.EU)
        self.setup_notifications(Region.NA)

        self.initialized = True

    # The actual ingame time!
    def ingame_time(self, region):
        return datetime.now(timezone.utc) + timedelta(hours=self.region_configs[region]["tz"])

    # Initialize notifications
    def setup_notifications(self, region):
        self.cronTab = []

        config = self.region_configs[region]
        channelId = config["channelId"]
        tz = config["tz"]
        role = config["role"]

        self.add_notification(
            "30 11,17,20 * * * 0",
            tz,
            self.com_channels[channelId],
            region,
            "Energy to be claimed! Go go!",
        )

        self.add_notification(
            "0 12 * * 1,4 0",
            tz,
            self.com_channels[channelId],
            region,
            "Dragon is invading! Remember to fix ballista!",
        )
        self.add_notification(
            "30 20 * * 1,4 0",
            tz,
            self.com_channels[channelId],
            region,
            "Dragon is leaving in 30 minutes! Remember to fix ballista!",
        )

        self.add_notification(
            "0 21 * * * 0",
            tz,
            self.com_channels[channelId],
            region,
            "Guild reward packs! Go claim some lewt!",
        )

        self.add_notification(
            "45 20 * * * 0", 
            tz,
            self.com_channels[channelId],
            region,
            "15 minutes to arena rewards",
        )

        self.add_notification(
            "15 21 * * * 0",
            tz,
            self.com_channels[channelId],
            region,
            "15 minutes to underground rewards! Go get em castles :partying_face:",
        )

        self.add_notification(
            "0 5 * * 3 0",
            tz,
            self.com_channels[channelId],
            region,
            "Sphinx is coming today, save up some movement!",
        )
        self.add_notification(
            "0 9 * * 3 0",
            tz,
            self.com_channels[channelId],
            region,
            "Sphinx is here, go play trivia!",
        )

        # KvK
        self.add_notification(
            "45 8 * * 3 0",
            tz,
            self.com_channels[channelId],
            region,
            f"15 minutes to KvK starts!! {role}",
        )
        self.add_notification(
            "45 8 * * 4,5 0",
            tz,
            self.com_channels[channelId],
            region,
            "15 minutes till today's KvK rounds start!",
        )
        self.add_notification(
            "45 21 * * 3,4 0",
            tz,
            self.com_channels[channelId],
            region,
            "15 minutes to KvK rewards! Go get em Kingdoms :partying_face:",
        )
        self.add_notification(
            "45 21 * * 5 0",
            tz,
            self.com_channels[channelId],
            region,
            "15 minutes to KvK ends! Go get em Kingdoms :partying_face:",
        )

        # BoG
        self.add_notification(
            "45 19 * * 2 0",
            tz,
            self.com_channels[channelId],
            region,
            "15 minutes to group game in BoG! Remember rosters!",
            StackedBot.bog_week,
        )
        self.add_notification(
            "45 19 * * 3 0",
            tz,
            self.com_channels[channelId],
            region,
            "15 minutes to Battle of Gods quarter finals! Go place your bets and rosters :partying_face:",
            StackedBot.bog_week,
        )
        self.add_notification(
            "45 19 * * 4 0",
            tz,
            self.com_channels[channelId],
            region,
            "15 minutes to Battle of Gods finals! Go place your bets and rosters :partying_face:",
            StackedBot.bog_week,
        )

        # CoG
        self.add_notification(
            "15 19 * * 2 0",
            tz,
            self.com_channels[channelId],
            region,
            "15 minutes to qualification games in CoG! Remember rosters!",
            StackedBot.cog_week,
        )
        self.add_notification(
            "15 19 * * 3 0",
            tz,
            self.com_channels[channelId],
            region,
            "15 minutes to qualification games in CoG  Remember rosters",
            StackedBot.cog_week,
        )
        self.add_notification(
            "15 19 * * 4 0",
            tz,
            self.com_channels[channelId],
            region,
            "15 minutes to CoG finals! Go place your bets and rosters :partying_face:",
            StackedBot.cog_week,
        )

        # Endless inferno
        self.add_notification(
            "0 9 * * 1,4 0",
            tz,
            self.com_channels[channelId],
            region,
            '"Endless" inferno is here, go climb the ladder!',
        )
        self.add_notification(
            "30 11 * * 1,4 0",
            tz,
            self.com_channels[channelId],
            region,
            '"Endless" inferno refresh in 30 minutes!',
        )

        # Mystical store
        self.add_notification(
            "0 5,12,18,21 * * * 0",
            tz, 
            None,
            region,
            "mystical",
        )

        # Emblem refresh
        self.add_notification(
            "0 5,8,11,14,17,20,23 * * * 0",
            tz,
            None,
            region,
            "emblem",
        )

        # Premium Cards
        self.add_notification(
            "0 5 1 * * 0",
            tz,
            self.com_channels[channelId],
            region,
            f"New premium deck out! Activate it BEFORE starting dailies! {role}",
        )

    # Wrapper for adding notifications
    def add_notification(self, time, tz, channel, region, message, active=None):
        self.cronTab.append(
            aiocron.crontab(
                time,
                func=partial(
                    StackedBot.send_notification, self, channel, region, message, active
                ),
                start=True,
                tz=timezone(timedelta(hours=tz)),
            )
        )

    # Return true if qualifying_week for BoG
    # def qualifying_week(self, region):
    #     now = self.ingame_time(region)
    #     year, week_num, day_of_week = now.isocalendar()
    #     qualifying_week = week_num % 2
    #     return not qualifying_week

    # Return true if CoG week
    def cog_week(self, region):
        now = self.ingame_time(region)
        year, week_num, day_of_week = now.isocalendar()
        return week_num % 2 == 0

    # Return true if BoG week
    def bog_week(self, region):
        return not self.cog_week(region)

    # Send notifications
    async def send_notification(self, channel, region, msg, active=None):
        if active is not None and active(self, region) and channel is not None:
            await channel.send(f"{msg}")
        elif active is None and channel is not None:
            await channel.send(f"{msg}")
        elif active is None and channel is None:
            message = f"{msg.capitalize()} store has refreshed"
            for id in self.remind_me[msg]:
                user = self.guilds[0].get_member(id)
                if user and self.region_configs[region]["role"] in user.roles:
                    await user.send(message)

    # Reaction translation stuff
    async def on_raw_reaction_add(self, reactionEvent):
        country = None
        try:
            country = flag.dflagize(reactionEvent.emoji.name)
            if ":" in country:
                country = country.replace(":", "").lower()
            else:
                country = None
        except:
            return

        if country is None:
            return

        try:
            language = self.countryToLanguage[country][0]

            channel = self.get_channel(reactionEvent.channel_id)
            message = await channel.fetch_message(reactionEvent.message_id)

            # Check for duplicate reaction
            for reaction in message.reactions:
                if reaction.emoji == reactionEvent.emoji.name and reaction.count != 1:
                    return

            translated = self.translator.translate(message.content, dest=language)

            await message.channel.send(
                f'"{message.content}" in {translated.dest} is: ```{translated.text}```'
            )
        except ValueError as e:
            print(f"tried translate to {language}")

            if str(e) == "invalid destination language":
                await message.channel.send(f"I can't translate into {language} yet!")
        except:
            print(f"tried translate to {language}")
            print(f"msg: {message.reactions}")

    # Member join handler
    async def on_member_join(self, member):
        await self.com_channels["lobby"].send(
            f"Hi {member.mention}, welcome to Stacked! :partying_face:"
        )

    # Message handler
    async def on_message(self, message):
        if message.author == client.user:
            return

        mentioned = self.user in message.mentions
        private = message.channel.type is discord.ChannelType.private
        msg = message.content.lower()

        if msg.startswith("!"):
            response = await self.handle_command(msg, message)
            if response is not None:
                await message.channel.send(f"{response}")
            return

        response = self.chatbot_process(message, reply=mentioned or private)
        if response is not None:
            if not private:
                response = f"{message.author.mention} {response}"
            await message.channel.send(response)

    # Prepare a response when I'm mentioned! (chatbot)
    def chatbot_process(self, message, reply=False):
        msg = self.clean_message(message)
        if msg is None:
            return None

        # TODO: This needs to be postponed, messages from various channels
        # come asynchronously, and will need to be ordered so bot can make
        # sense out of it. Make persistent dictionary, with message ID's from
        # where in each of channels it has read so far. Then hourly, check for updates.
        if reply is False:
            self.trainer.train([msg])
            return None

        return self.bot.get_response(msg)

    # Command switch
    async def handle_command(self, msg, full_message):
        response = None
        if msg.startswith("!help"):
            response = self.help(msg)
        elif msg.startswith("!event"):
            response = self.events_message(msg)
        elif msg.startswith("!kvkcalc"):
            response = self.kvk_calc(msg)
        elif (
            msg.startswith("!addis")
            or msg.startswith("!whatis")
            or msg.startswith("!remis")
        ):
            response = self.handle_is(msg)
        # elif msg.startswith('!db'):
        # 	response = self.handle_sheet(msg)
        elif msg.startswith("!lookup"):
            response = self.wikipedia_lookup(msg)
        elif msg.startswith("!urban"):
            response = self.urban_lookup(msg)
        elif msg.startswith("!inspireme"):
            response = self.inspireme(msg)
        elif msg.startswith("!remindme"):
            response = self.handle_remind_me(full_message)
        elif msg.startswith("!role"):
            response = await self.handle_role(full_message)
        return response

    # Reminder registration
    def handle_remind_me(self, message):
        valid_events = ["emblem", "mystical"]
        msg = message.content.lower()
        event = msg.split()
        if len(event) == 1:
            return 'What event you want to be reminded of? "emblem" or "mystical"?'
        event_name = event[1]
        if event_name not in valid_events:
            return "Don't know that event..."

        if event_name not in self.remind_me:
            self.remind_me[event_name] = []

        if message.author.id in self.remind_me[event_name]:
            self.remind_me[event_name].remove(message.author.id)
            return f"I'll stop reminding you of {event_name}"
        else:
            self.remind_me[event_name].append(message.author.id)
            return f"I'll remind you of {event_name}"

    # Role registration
    async def handle_role(self, message):
        valid_roles = ["EU", "NA"]
        msg = message.content
        role_raw = msg.split()
        if len(role_raw) == 1:
            return 'What role you want to be added to? "EU" or "NA"?'
        role_name = role_raw[1]
        if role_name not in valid_roles:
            return "Don't know that role... (supported 'EU' and 'NA')"

        role = self.region_configs[Region[role_name.upper()]]["role"]
        if role in message.author.roles:
            await message.author.remove_roles(role)
            return f"I'll stop notifying you of {role_name} events"
        else:
            await message.author.add_roles(role)
            return f"I'll remind you of {role_name} events"

    # HALP!
    def help(self, message):
        response = f"Version {get_version()}\n"
        response += "!event <Region=[Default:EU, NA]> - Todays events\n"
        response += "!events <Region=[Default:EU, NA]> - This weeks events\n"
        response += "!whatis <keyword> - Explains what keyword is\n"
        response += "!addis <keyword> <explanation> - Teach me what keyword means\n"
        response += "!remis <keyword> - Deletes my knowledge of keyword\n"
        response += (
            "!kvkcalc <OurCurrent> <TheirCurrent> <OurGain1> <TheirGain1> "
            "<OurGain2> <TheirGain2> <OurGain3> <TheirGain3> <Region=[Default:EU, NA]> - See if we win KvK\n"
        )
        response += (
            "React to a message with your flag, and I'll translate that for you\n"
        )
        response += "!lookup <stuff> - I'll lookup stuff on Wikipedia\n"
        response += "!urban <stuff> - I'll lookup stuff on Urban Dictionary\n"
        response += "!inspireme - I'll generate an inspirational quote\n"
        response += "!remindme <event> - I'll notify you about event in pm\n"
        response += "!role <EU/NA> - I'll notify you about events for that region in pm\n"
        response += "Mention me and I'll respond something stupid :partying_face:"

        return response

    # Handle the _is stuff
    def handle_is(self, message):
        if message.startswith("!whatis"):
            keyword = message.split()[1].lower()
            if keyword in self.whatis:
                return f"{keyword} refers to {self.whatis[keyword]}"
            else:
                return f"I don't know what {keyword} means..."
        elif message.startswith("!addis"):
            meh, keyword, meaning = message.split(" ", 2)
            self.whatis[keyword.lower()] = meaning
            return f"Thanks for letting me know what {keyword} means"
        elif message.startswith("!remis"):
            keyword = message.split()[1].lower()
            del self.whatis[keyword]
            return f"I've forgotten what {keyword} means"

    # Do a wiki lookup
    def wikipedia_lookup(self, query):
        keywords = query.split(" ", 1)
        if len(keywords) == 1:
            return "what do you want me to lookup?"

        keyword = keywords[1]

        try:
            return wikipedia.summary(keyword).split(".")[0]
        except Exception:
            try:
                for newquery in wikipedia.search(keyword):
                    try:
                        return wikipedia.summary(newquery).split(".")[0]
                    except:
                        pass
            except:
                pass
        return "I don't know about " + keyword

    def urban_lookup(self, query):
        """
        Urban dictionary lookup
        Returns the definition (and example) with the most "thumbs_up"
        """
        keywords = query.split(" ", 1)
        if len(keywords) == 1:
            return "what do you want me to lookup?"

        keyword = keywords[1]

        try:
            url = "https://mashape-community-urban-dictionary.p.rapidapi.com/define"
            querystring = {"term": keyword}
            headers = {
                "x-rapidapi-key": f"{URBAN_DICTIONARY_API_KEY}",
                "x-rapidapi-host": "mashape-community-urban-dictionary.p.rapidapi.com",
            }
            response = requests.request("GET", url, headers=headers, params=querystring)
            response_list = json.loads(response.content)["list"]
            item = max(response_list, key=lambda item: int(item["thumbs_up"]))
            result = (
                f"**Definition**: {item['definition']}\n**Example**: {item['example']}"
            )
            return result[:DISCORD_CHAR_LIMIT]
        except Exception as ex:
            pass
        return "I don't know about " + keyword

    def inspireme(self, message):
        """inspirobot.me quote"""
        try:
            quote = inspirobot.generate()  # Generate Image
            return quote.url
        except Exception as ex:
            pass
        return "Something went wrong :poop:"

    # Calculates progression in KvK based on current situation
    def kvk_calc(self, message):
        components = message.split()
        region = Region.EU
        if len(components) < 9 or len(components) > 10:
            return (
                "Usage: !kvkcalc <OurCurrent> <TheirCurrent> <OurGain1> "
                "<TheirGain1> <OurGain2> <TheirGain2> <OurGain3> <TheirGain3> <Region=[Default:EU, NA]>"
            )
        try:
            ourCurrent = int(components[1])
            theirCurrent = int(components[2])
            ourGain = [int(components[3]), int(components[5]), int(components[7])]
            theirGain = [int(components[4]), int(components[6]), int(components[8])]
            if len(components) == 10:
                region = Region[components[9].upper()]
        except:
            return "Could not understand that.."

        now = self.ingame_time(region)
        remainingTime = 22.0 - now.hour + (now.minute / 60)

        ourGoal = ourCurrent + sum([arena * remainingTime for arena in ourGain])
        theirGoal = theirCurrent + sum([arena * remainingTime for arena in theirGain])

        diff = ourGoal - theirGoal
        response = f"At the end of the day we'll be at {int(ourGoal)} and they at {int(theirGoal)}, "
        if diff > 0:
            response += " we're leading by "
        else:
            response += " we're loosing by "
            diff = theirGoal - ourGoal

        response += f"{int(diff)}"
        return response

    # Prepares message containing respose to !events
    def events_message(self, msg):
        components = msg.split()
        region = Region.EU
        if len(components) < 1 or len(components) > 2:
            return (
                "Usage: !event(s) <Region=[Default:EU, NA]>"
            )
        try:
            if len(components) == 2:
                region = Region[components[1].upper()]
        except:
            return "Could not understand that.."

        now = self.ingame_time(region)
        year, week_num, day_of_week = now.isocalendar()
        cog_week = week_num % 2 == 0

        daily = not msg.startswith("!events")

        if daily:
            response = "Todays events:```\n"
        else:
            response = "This weeks events:```\n"

        week_battle = "Cross-server Clash of Gods" if cog_week else "Battle of the Gods"

        if not daily:
            response += week_battle + "!\n"

        if daily:
            if day_of_week == 2:
                if cog_week:
                    response += "Qualifications Day 1 in " + week_battle + "\n"
                else:
                    response += "Group game in " + week_battle + "\n"
            elif day_of_week == 3:
                if cog_week:
                    response += "Qualifications Day 2 in " + week_battle + "\n"
                else:
                    response += "Quarter finals in " + week_battle + "\n"
            elif day_of_week == 4:
                if cog_week:
                    response += "Final in " + week_battle + "\n"
                else:
                    response += "Final " + week_battle + "\n"

        if daily and day_of_week in [1, 4]:
            response += "Dragon invasion\n"
        elif not daily:
            response += "Monday and Thursday - Dragon invasion\n"

        if daily and day_of_week == 3:
            response += "0900 - 2100: Sphinx is asking questions\n"

        if daily and day_of_week in [3, 4, 5]:
            response += "0900 - 22:00: Kingdom vs Kingdom!\n"
        elif not daily:
            response += "Wednesday 0900 - 2100: Sphinx is asking questions\n"
            response += "Wednesday 0900 - Kingdom vs Kingdom starts!\n"
            response += "Friday 2200    - Kingdom vs Kingdom ends\n"

        if daily and day_of_week in [6, 7]:
            response += "Dragon Utopia is open :gem:\n"
        elif not daily:
            response += "Saturday and Sunday - Dragon Utopia is open :gem:\n"

        response += "```"
        return response


def get_version():
    """Returns the bot version as the timestamp of this file"""

    fname = pathlib.Path(__file__)
    if fname.exists():
        mtime = datetime.fromtimestamp(fname.stat().st_mtime)
        return mtime.strftime("%Y-%m-%d %H:%M")
    else:
        return "?"


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    client = StackedBot()
    client.run(token)
