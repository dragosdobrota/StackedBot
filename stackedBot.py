import os
import shelve

# Datetime calculations
from datetime import datetime, timedelta, timezone
from functools import partial

# Support for notifications
import aiocron
import discord
import flag

# Wikipedia lookups
import wikipedia

# Chat bot
from chatterbot import ChatBot, languages
from chatterbot.trainers import ChatterBotCorpusTrainer, ListTrainer

# Load environment
from dotenv import load_dotenv

# Translation support
from googletrans import Translator

# Google sheet integration
# from apiclient import discovery
# from google.oauth2 import service_account
# SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
# SPREAD_SHEET='1ksHbbJGGaPI4ytMUeXfNmy33ejuw3YznP4XDor1GaMA'
BOT_VERSION = "20210327,1340"


load_dotenv()

# Fixing spacy at runtime, it is required to previously call 'python -m spacy download en'
languages.ENG.ISO_639_1 = 'en_core_web_sm'

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
        super().__init__(intents=intents)

        # Channels
        self.com_channels = {
            "guild": None,
            "server": None,
            "public": None,
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
        self.initialize_bot = False
        self.initialize_with_corpus = True

    # Clean message string
    def clean_message(self, message):
        msg = message.clean_content
        try:
            if msg.startswith(">"):
                msg = msg.split("\n")[1]
            if msg.startswith("@"):
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

        self.everyone = self.guilds[0].default_role

        self.com_channels["guild"] = self.guilds[0].get_channel(
            int(os.getenv("GUILD_CHANNEL"))
        )
        self.com_channels["server"] = self.guilds[0].get_channel(
            int(os.getenv("SERVER_CHANNEL"))
        )
        self.com_channels["public"] = self.guilds[0].get_channel(
            int(os.getenv("PUBLIC_CHANNEL"))
        )
        self.com_channels["lobby"] = self.guilds[0].get_channel(
            int(os.getenv("LOBBY_CHANNEL"))
        )

        for channel in self.com_channels:
            if self.com_channels[channel] is None:
                print(f"Could not find {channel} channel")
                quit()

        print(f"{self.user.name} has connected to {self.guilds}!")

        # Setup notifications
        self.setup_notifications()

        # Train bot if needed
        if self.initialize_bot:
            await self.train_bot()

        self.initialized = True

    # Train the bot from our history, and perhaps a corpus
    async def train_bot(self):
        if self.initialize_with_corpus:
            corpTrainer = ChatterBotCorpusTrainer(self.bot)
            corpTrainer.train(
                "chatterbot.corpus.english.ai",
                "chatterbot.corpus.english.botprofile",
                "chatterbot.corpus.english.computers",
                "chatterbot.corpus.english.conversations",
                "chatterbot.corpus.english.emotion",
                "chatterbot.corpus.english.food",
                "chatterbot.corpus.english.gossip",
                "chatterbot.corpus.english.greetings",
                "chatterbot.corpus.english.health",
                "chatterbot.corpus.english.history",
                "chatterbot.corpus.english.humor",
                "chatterbot.corpus.english.literature",
                "chatterbot.corpus.english.money",
                "chatterbot.corpus.english.movies",
                "chatterbot.corpus.english.politics",
                "chatterbot.corpus.english.psychology",
                "chatterbot.corpus.english.science",
                "chatterbot.corpus.english.sports",
                "chatterbot.corpus.english.trivia",
            )
        print("Some history")
        for channel in self.guilds[0].channels:
            if channel.type is discord.ChannelType.text:
                print(f"reading history for {channel.name}")
                history = []
                try:
                    async for message in channel.history(limit=None, oldest_first=True):
                        if message.author != client.user:
                            msg = self.clean_message(message)
                            if msg is not None:
                                history.append(msg)
                except:
                    pass

                print(f"Training set {channel.name}: {len(history)}")
                self.trainer.train(history)
        print("history done")

    # The actual ingame time!
    def ingame_time(self):
        return datetime.now(timezone.utc) + timedelta(hours=1)

    # Initialize notifications
    def setup_notifications(self):
        self.cronTab = []

        self.add_notification(
            "30 11,17,20 * * * 0",
            self.com_channels["public"],
            "Energy to be claimed! Go go!",
        )

        self.add_notification(
            "0 12 * * 1,4 0",
            self.com_channels["public"],
            "Dragon is invading! Remember to fix ballista!",
        )
        self.add_notification(
            "30 20 * * 1,4 0",
            self.com_channels["public"],
            "Dragon is leaving in 30 minutes! Remember to fix ballista!",
        )

        self.add_notification(
            "0 21 * * * 0",
            self.com_channels["public"],
            "Guild reward packs! Go claim some lewt!",
        )

        self.add_notification(
            "45 20 * * * 0", self.com_channels["public"], "15 minutes to arena rewards"
        )

        self.add_notification(
            "15 21 * * * 0",
            self.com_channels["guild"],
            "15 minutes to underground rewards! Go get em castles :partying_face:",
        )

        self.add_notification(
            "0 5 * * 3 0",
            self.com_channels["public"],
            "Sphinx is coming today, save up some movement!",
        )
        self.add_notification(
            "0 9 * * 3 0",
            self.com_channels["public"],
            "Sphinx is here, go play trivia!",
        )

        # KvK
        self.add_notification(
            "45 8 * * 3 0",
            self.com_channels["server"],
            f"15 minutes to KvK starts!! {self.everyone}",
        )
        self.add_notification(
            "45 8 * * 4,5 0",
            self.com_channels["server"],
            "15 minutes till today's KvK rounds start!",
        )
        self.add_notification(
            "45 21 * * 3,4 0",
            self.com_channels["server"],
            "15 minutes to KvK rewards! Go get em Kingdoms :partying_face:",
        )
        self.add_notification(
            "45 21 * * 5 0",
            self.com_channels["server"],
            "15 minutes to KvK ends! Go get em Kingdoms :partying_face:",
        )

        # BoG
        self.add_notification(
            "45 19 * * 2 0",
            self.com_channels["public"],
            "15 minutes to group game in BoG! Remember rosters!",
            StackedBot.bog_week,
        )
        self.add_notification(
            "45 19 * * 3 0",
            self.com_channels["public"],
            "15 minutes to Battle of Gods quarter finals! Go place your bets and rosters :partying_face:",
            StackedBot.bog_week,
        )
        self.add_notification(
            "45 19 * * 4 0",
            self.com_channels["public"],
            "15 minutes to Battle of Gods finals! Go place your bets and rosters :partying_face:",
            StackedBot.bog_week,
        )

        # CoG
        self.add_notification(
            "15 19 * * 2 0",
            self.com_channels["public"],
            "15 minutes to qualification games in CoG! Remember rosters!",
            StackedBot.cog_week,
        )
        self.add_notification(
            "15 19 * * 3 0",
            self.com_channels["public"],
            "15 minutes to qualification games in CoG  Remember rosters",
            StackedBot.cog_week,
        )
        self.add_notification(
            "15 19 * * 4 0",
            self.com_channels["public"],
            "15 minutes to CoG finals! Go place your bets and rosters :partying_face:",
            StackedBot.cog_week,
        )

        # Endless inferno
        self.add_notification(
            "0 9 * * 1,4 0",
            self.com_channels["public"],
            '"Endless" inferno is here, go climb the ladder!',
        )
        self.add_notification(
            "30 11 * * 1,4 0",
            self.com_channels["public"],
            '"Endless" inferno refresh in 30 minutes!',
        )

        # Mystical store
        self.add_notification("0 5,12,18,21 * * * 0", None, "mystical")

        # Emblem refresh
        self.add_notification("0 5,8,11,14,17,20,23 * * * 0", None, "emblem")

        # Premium Cards
        self.add_notification(
            "0 5 1 * * 0",
            self.com_channels["public"],
            f"New premium deck out! Activate it BEFORE starting dailies! {self.everyone}",
        )

    # Wrapper for adding notifications
    def add_notification(self, time, channel, message, active=None):
        self.cronTab.append(
            aiocron.crontab(
                time,
                func=partial(
                    StackedBot.send_notification, self, channel, message, active
                ),
                start=True,
                tz=timezone(timedelta(hours=1)),
            )
        )

    # Return true if qualifying_week for BoG
    # def qualifying_week(self):
    #     now = self.ingame_time()
    #     year, week_num, day_of_week = now.isocalendar()
    #     qualifying_week = week_num % 2
    #     return not qualifying_week

    # Return true if CoG week
    def cog_week(self):
        now = self.ingame_time()
        year, week_num, day_of_week = now.isocalendar()
        return week_num % 2 == 0

    # Return true if BoG week
    def bog_week(self):
        return not self.cog_week()

    # Send notifications
    async def send_notification(self, channel, msg, active=None):
        if active is not None and active(self) and channel is not None:
            await channel.send(f"{msg}")
        elif active is None and channel is not None:
            await channel.send(f"{msg}")
        elif active is None and channel is None:
            message = f"{msg.capitalize()} store has refreshed"
            for id in self.remind_me[msg]:
                user = self.guilds[0].get_member(id)
                if user:
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
            response = self.handle_command(msg, message)
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
    def handle_command(self, msg, full_message):
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
        elif msg.startswith("!remindme"):
            response = self.handle_remind_me(full_message)
        return response

    # Reminder registration
    def handle_remind_me(self, message):
        valid_events = ["emblem", "mystical"]
        msg = message.content.lower()
        event = msg.split()
        if len(event) == 1:
            return 'What event you want to be reminded of? "emblem" or "mystical"?'
        if event[1] not in valid_events:
            return "Don't know that event..."

        if event[1] not in self.remind_me:
            self.remind_me[event[1]] = []

        if message.author.id in self.remind_me[event[1]]:
            self.remind_me[event[1]].remove(message.author.id)
            return f"I'll stop reminding you of {event[1]}"
        else:
            self.remind_me[event[1]].append(message.author.id)
            return f"I'll remind you of {event[1]}"

    # HALP!
    def help(self, message):
        response = f"Version {BOT_VERSION}\n"
        response += "!event  - Todays events\n"
        response += "!events - This weeks events\n"
        response += "!whatis <keyword> - Explains what keyword is\n"
        response += "!addis <keyword> <explanation> - Teach me what keyword means\n"
        response += "!remis <keyword> - Deletes my knowledge of keyword\n"
        response += (
            "!kvkcalc <OurCurrent> <TheirCurrent> <OurGain1> <TheirGain1> "
            "<OurGain2> <TheirGain2> <OurGain3> <TheirGain3> - See if we win KvK\n"
        )
        response += (
            "React to a message with your flag, and I'll translate that for you\n"
        )
        response += "!lookup <stuff> - I'll lookup stuff on wikipedia\n"
        response += "!remindme <event> - I'll notify you about event in pm\n"
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
            return "what do you wan't me to lookup?"

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

    # Calculates progression in KvK based on current situation
    def kvk_calc(self, message):
        components = message.split()
        if len(components) != 9:
            return (
                "Usage: !kvkcalc <OurCurrent> <TheirCurrent> <OurGain1> "
                "<TheirGain1> <OurGain2> <TheirGain2> <OurGain3> <TheirGain3>"
            )
        try:
            ourCurrent = int(components[1])
            theirCurrent = int(components[2])
            ourGain = [int(components[3]), int(components[5]), int(components[7])]
            theirGain = [int(components[4]), int(components[6]), int(components[8])]
        except:
            return "Could not understand that.."

        now = self.ingame_time()
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
        now = self.ingame_time()
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
            response += "Dragon utopia is open :gem:\n"
        elif not daily:
            response += "Saturday and Sunday - Dragon utopia is open :gem:\n"

        response += "```"
        return response


if __name__ == "__main__":
    token = os.getenv("DISCORD_TOKEN")
    client = StackedBot()
    client.run(token)
