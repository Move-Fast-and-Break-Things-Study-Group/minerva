import os
from typing import Dict, List
import discord
import openai
from dotenv import load_dotenv
import tiktoken

from minerva.markdown_splitter import split_markdown

load_dotenv()

openai.api_key = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = "gpt-3.5-turbo-0613"
GUILD_ID_STR = os.getenv("GUILD_ID")
if GUILD_ID_STR is None:
  raise ValueError("GUILD_ID environment variable is not set")
GUILD_ID = int(GUILD_ID_STR)
MAX_DISCORD_MESSAGE_LENGTH_CHAR = 2000

AI_NAME = "Minerva"
AI_USER_ID_PLACEHOLDER = "<bot_user_id>"

PROMPT = f"""You are {AI_NAME}, she/her, a Discord AI assistant whose purpose is to guide and mentor aspiring software and machine learning engineers to enhance their skills and knowledge. You are good at breaking down intricate concepts and explaining them in a clear and understandable manner. You are highly effective as a teacher. You are friendly and respectful. When giving a response, you find the sources, base your response on them, and reference them. You will politely decline to answer any question or fulfill any request unrelated to learning.

If it makes sense, instead of providing a solution, nudge the user to think about the problem and come up with a solution themselves.

The conversation history will include multiple participants, and each message is structured as follows:
participant id: message content

Your user id is: {AI_USER_ID_PLACEHOLDER}. When mentioning a participant, use the following format (include angle brackets): <@participant id>. Never mention yourself. Always answer in the language of the last message you are responding to, don't provide translations of your messages.

Use markdown to format quotes, code blocks, bold, italics, underline, and strikethrough text. Only these markdown rules are supported.

CONVERSATION HISTORY:
"""  # noqa: E501


TOKENIZER = tiktoken.encoding_for_model(OPENAI_MODEL)


class Message:
  def __init__(self, author, content):
    self.author = author
    self.content = content
    self.len_tokens = len(TOKENIZER.encode(str(self)))

  def __str__(self):
    return f"{self.author}: {self.content}"


class MessageHistory:
  def __init__(self, bot_id, token_limit=1920):
    self.bot_id = bot_id
    self.token_limit = token_limit
    self.history: List[Message] = []
    self.current_tokens = len(TOKENIZER.encode(self.format_prompt()))

  def add(self, message: Message):
    self.history.append(message)
    self.current_tokens += message.len_tokens
    while self.current_tokens > self.token_limit:
      deleted_message = self.history.pop(0)
      self.current_tokens -= deleted_message.len_tokens

  def format_prompt(self):
    prompt = PROMPT.replace(AI_USER_ID_PLACEHOLDER, str(self.bot_id))
    for message in self.history:
      prompt += f"\n{message}\n"
    prompt += "\nYour response:"
    return prompt


class MyClient(discord.Client):
  def __init__(self, *args, **kwargs):
    super().__init__(*args, **kwargs)
    self.chat_histories: Dict[int, MessageHistory] = {}

  async def on_ready(self):
    print(f'Logged on as {self.user}!')

  async def on_guild_join(self, guild):
    if guild.id != GUILD_ID:
      await guild.leave()

  async def on_message(self, message: discord.Message):
    if not self.user or message.author == self.user:
      # Ignore messages from self
      return
    if not message.channel.type \
        or message.channel.type.name not in ["text", "forum", "public_thread"]:
      # Ignore messages from non-text channels
      return
    # Add message to chat history
    if message.channel.id not in self.chat_histories:
      self.chat_histories[message.channel.id] = MessageHistory(self.user.id)
    chat_history = self.chat_histories[message.channel.id]
    chat_history.add(Message(message.author.id, message.content))
    # Don't respond if not mentioned explicitly
    if self.user not in message.mentions:
      return

    async with message.channel.typing():
      try:
        response = await openai.ChatCompletion.acreate(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": chat_history.format_prompt()},
            ],
            temperature=0.6,
            max_tokens=2048,
            user=f"discord-{message.author.id}",
        )
        answer = response.choices[0].message.content  # type: ignore
      except Exception as err:
        print("OpenAI API error:", err)
        answer = (
          "I'm sorry, I'm having trouble understanding you right now."
          " Could you please rephrase your question?"
        )

      chat_history.add(Message(self.user.id, answer))

      for response in split_markdown(answer, MAX_DISCORD_MESSAGE_LENGTH_CHAR):
        await message.channel.send(response, reference=message)


def main():
  intents = discord.Intents.default()
  intents.message_content = True

  client = MyClient(intents=intents)
  discord_token = os.getenv("DISCORD_TOKEN")
  if not discord_token:
    raise ValueError("DISCORD_TOKEN environment variable is not set")
  client.run(discord_token)


if __name__ == "__main__":
  main()
