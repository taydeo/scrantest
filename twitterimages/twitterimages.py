
import discord
from redbot.core import commands, Config
import asyncio
import requests
import random

class TwitterImages(commands.Cog):
    """Pull latest images from a Twitter account."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {"twitter_username": None, "cached_images": []}
        self.config.register_guild(**default_guild)
        self.scrape_task = bot.loop.create_task(self.scrape_loop())

    async def fetch_images(self, username: str, count: int = 200):
        url = f"https://cdn.syndication.twimg.com/timeline/profile?screen_name={username}&count={count}"
        r = requests.get(url, timeout=10)
        data = r.json()
        images = []

        for instruction in data.get("instructions", []):
            entries = instruction.get("addEntries", {}).get("entries", [])
            for entry in entries:
                content = entry.get("content", {})
                tweet = content.get("item", {}).get("content", {}).get("tweet", {})
                media = tweet.get("mediaDetails", [])
                for m in media:
                    if m.get("type") == "photo":
                        images.append(m.get("media_url_https"))

        return images

    @commands.group()
    @commands.admin_or_permissions(manage_guild=True)
    async def twitterset(self, ctx):
        """Twitter settings."""
        pass

    @twitterset.command()
    async def username(self, ctx, username: str):
        await self.config.guild(ctx.guild).twitter_username.set(username)
        await ctx.send(f"Twitter username set to `{username}`.")

    @commands.command(name="scran")
    async def scran(self, ctx):
        cached = await self.config.guild(ctx.guild).cached_images()
        if not cached:
            return await ctx.send("Cache empty. Scraper may not have run yet.")
        choice = random.choice(cached)
        embed = discord.Embed()
        embed.set_image(url=choice)
        await ctx.send(embed=embed)

    async def scrape_loop(self):
        await self.bot.wait_until_ready()
        while True:
            for guild in self.bot.guilds:
                username = await self.config.guild(guild).twitter_username()
                if not username:
                    continue
                try:
                    imgs = await self.fetch_images(username, 200)
                    if imgs:
                        await self.config.guild(guild).cached_images.set(imgs)
                except Exception:
                    pass
            await asyncio.sleep(900)
