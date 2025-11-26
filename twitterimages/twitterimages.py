import discord
from redbot.core import commands, Config
import asyncio
import requests
import random
import logging
import time

class TwitterImages(commands.Cog):
    """Pull latest images from a Twitter account."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {"twitter_username": None, "cached_images": []}
        self.config.register_guild(**default_guild)
        
        # Set up logger
        self.logger = logging.getLogger('red.TwitterImages')
        self.last_run_time = None
        
        self.scrape_task = bot.loop.create_task(self.scrape_loop())

    async def fetch_images(self, username: str, count: int = 200):
        self.logger.debug(f"Fetching images for username: {username}")
        url = f"https://cdn.syndication.twimg.com/timeline/profile?screen_name={username}&count={count}"
        try:
            r = requests.get(url, timeout=10)
            r.raise_for_status()
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

            self.logger.info(f"Successfully fetched {len(images)} images for {username}")
            return images
        except Exception as e:
            self.logger.error(f"Error fetching images for {username}: {str(e)}")
            return []

    @commands.group()
    @commands.admin_or_permissions(manage_guild=True)
    async def twitterset(self, ctx):
        """Twitter settings."""
        pass

    @twitterset.command()
    async def username(self, ctx, username: str):
        await self.config.guild(ctx.guild).twitter_username.set(username)
        await ctx.send(f"Twitter username set to `{username}`.")
        self.logger.info(f"Twitter username set to {username} in guild {ctx.guild.id}")

    @commands.command(name="scran")
    async def scran(self, ctx):
        cached = await self.config.guild(ctx.guild).cached_images()
        if not cached:
            self.logger.warning(f"scran command used in guild {ctx.guild.id} but cache is empty")
            return await ctx.send("Cache empty. Scraper may not have run yet.")
        
        choice = random.choice(cached)
        embed = discord.Embed()
        embed.set_image(url=choice)
        await ctx.send(embed=embed)
        self.logger.debug(f"Sent random image from cache in guild {ctx.guild.id}")

    async def scrape_loop(self):
        await self.bot.wait_until_ready()
        self.logger.info("TwitterImages scraper loop started")
        
        while True:
            start_time = time.time()
            self.logger.info("Starting scrape cycle")
            
            guilds_processed = 0
            images_cached = 0
            
            for guild in self.bot.guilds:
                username = await self.config.guild(guild).twitter_username()
                if not username:
                    continue
                    
                try:
                    self.logger.debug(f"Scraping images for {username} in guild {guild.id}")
                    imgs = await self.fetch_images(username, 200)
                    if imgs:
                        await self.config.guild(guild).cached_images.set(imgs)
                        guilds_processed += 1
                        images_cached += len(imgs)
                        self.logger.info(f"Cached {len(imgs)} images for {username} in guild {guild.id}")
                    else:
                        self.logger.warning(f"No images found for {username} in guild {guild.id}")
                except Exception as e:
                    self.logger.error(f"Error scraping {username} in guild {guild.id}: {str(e)}")
            
            # Update last run time and log cycle completion
            self.last_run_time = time.time()
            cycle_duration = self.last_run_time - start_time
            
            self.logger.info(
                f"Scrape cycle completed: {guilds_processed} guilds processed, "
                f"{images_cached} total images cached, took {cycle_duration:.2f} seconds"
            )
            
            # Log warning if last run was more than 3 minutes ago (shouldn't happen but just in case)
            if self.last_run_time and (time.time() - self.last_run_time) > 180:
                self.logger.warning(
                    f"Scraper hasn't run for {time.time() - self.last_run_time:.2f} seconds. "
                    f"Expected interval: 900 seconds"
                )
            
            self.logger.info("Scraper going to sleep for 900 seconds (15 minutes)")
            await asyncio.sleep(900)

    def cog_unload(self):
        """Cancel the scrape task when the cog is unloaded."""
        self.scrape_task.cancel()
        self.logger.info("TwitterImages scraper loop stopped")
