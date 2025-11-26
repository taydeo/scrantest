import discord
from redbot.core import commands, Config
import asyncio
import requests
import random
import logging
import time
import json

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
            # Add headers to mimic a real browser
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            self.logger.debug(f"Making request to: {url}")
            r = requests.get(url, timeout=10, headers=headers)
            
            # Log response details for debugging
            self.logger.debug(f"Response status code: {r.status_code}")
            self.logger.debug(f"Response headers: {dict(r.headers)}")
            self.logger.debug(f"Response content length: {len(r.content)}")
            
            if r.status_code != 200:
                self.logger.error(f"HTTP error {r.status_code} for {username}: {r.text}")
                return []
            
            # Check if response is actually JSON
            if not r.text.strip():
                self.logger.error(f"Empty response for {username}")
                return []
                
            try:
                data = r.json()
            except json.JSONDecodeError as e:
                self.logger.error(f"JSON decode error for {username}: {e}")
                self.logger.error(f"Response text (first 500 chars): {r.text[:500]}")
                return []
            
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
            
        except requests.exceptions.Timeout:
            self.logger.error(f"Request timeout for {username}")
            return []
        except requests.exceptions.RequestException as e:
            self.logger.error(f"Request exception for {username}: {str(e)}")
            return []
        except Exception as e:
            self.logger.error(f"Unexpected error fetching images for {username}: {str(e)}")
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
        
        # Try to immediately fetch images for the new username
        try:
            self.logger.info(f"Immediately fetching images for new username: {username}")
            imgs = await self.fetch_images(username, 200)
            if imgs:
                await self.config.guild(ctx.guild).cached_images.set(imgs)
                await ctx.send(f"✅ Successfully cached {len(imgs)} images!")
            else:
                await ctx.send("❌ No images found. Check the username or try again later.")
        except Exception as e:
            self.logger.error(f"Error in immediate fetch for {username}: {str(e)}")
            await ctx.send("❌ Error fetching images. Check logs for details.")

    @commands.command(name="scran")
    async def scran(self, ctx):
        cached = await self.config.guild(ctx.guild).cached_images()
        username = await self.config.guild(ctx.guild).twitter_username()
        
        if not cached:
            self.logger.warning(f"scran command used in guild {ctx.guild.id} but cache is empty (username: {username})")
            return await ctx.send("Cache empty. Scraper may not have run yet or no images were found.")
        
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
            guilds_with_errors = 0

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
                        guilds_with_errors += 1
                except Exception as e:
                    self.logger.error(f"Error scraping {username} in guild {guild.id}: {str(e)}")
                    guilds_with_errors += 1
            
            # Update last run time and log cycle completion
            self.last_run_time = time.time()
            cycle_duration = self.last_run_time - start_time
            
            self.logger.info(
                f"Scrape cycle completed: {guilds_processed} guilds processed, "
                f"{guilds_with_errors} guilds with errors, "
                f"{images_cached} total images cached, took {cycle_duration:.2f} seconds"
            )
            
            # Log warning if last run was more than 3 minutes ago
            if self.last_run_time and (time.time() - self.last_run_time) > 180:
                self.logger.warning(
                    f"Scraper hasn't run for {time.time() - self.last_run_time:.2f} seconds. "
                    f"Expected interval: 900 seconds"
                )
            
            self.logger.info("Scraper going to sleep for 900 seconds (15 minutes)")
            await asyncio.sleep(900)

    def cog_unload(self):
        """Cancel the scrape task when the cog is unloaded."""
        if self.scrape_task:
            self.scrape_task.cancel()
        self.logger.info("TwitterImages scraper loop stopped")

    @commands.command()
    @commands.admin_or_permissions(manage_guild=True)
    async def force_scrape(self, ctx):
        """Force an immediate scrape for this server's Twitter username."""
        username = await self.config.guild(ctx.guild).twitter_username()
        if not username:
            return await ctx.send("No Twitter username set for this server.")
        
        await ctx.send(f"🔄 Force scraping images for `{username}`...")
        
        try:
            imgs = await self.fetch_images(username, 200)
            if imgs:
                await self.config.guild(ctx.guild).cached_images.set(imgs)
                await ctx.send(f"✅ Successfully cached {len(imgs)} images!")
            else:
                await ctx.send("❌ No images found. The username might be invalid or the account might not have any images.")
        except Exception as e:
            self.logger.error(f"Error in force_scrape for {username}: {str(e)}")
            await ctx.send("❌ Error fetching images. Check logs for details.")
