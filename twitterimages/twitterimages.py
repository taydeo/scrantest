import discord
from redbot.core import commands, Config
import asyncio
import aiohttp
import random
import logging
import time
import os

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
        
        # Twitter API Bearer Token - set this in your Redbot credentials
        self.bearer_token = None
        
        self.scrape_task = bot.loop.create_task(self.scrape_loop())

    async def initialize(self):
        """Initialize Twitter API token"""
        self.bearer_token = await self.bot.get_shared_api_tokens("twitter")
        if not self.bearer_token.get("bearer_token"):
            self.logger.warning("Twitter Bearer Token not set! Use [p]set api twitter bearer_token,YOUR_TOKEN")

    async def fetch_images_v2(self, username: str, count: int = 20):
        """Use Twitter API v2 to fetch images"""
        if not self.bearer_token:
            await self.initialize()
            
        bearer_token = self.bearer_token.get("bearer_token") if self.bearer_token else None
        if not bearer_token:
            self.logger.error("Twitter API bearer token not configured")
            return []

        # First, get user ID from username
        user_url = f"https://api.twitter.com/2/users/by/username/{username}"
        headers = {"Authorization": f"Bearer {bearer_token}"}
        
        try:
            async with aiohttp.ClientSession() as session:
                # Get user ID
                async with session.get(user_url, headers=headers) as response:
                    if response.status != 200:
                        self.logger.error(f"Error getting user ID: {response.status}")
                        return []
                    
                    user_data = await response.json()
                    user_id = user_data.get('data', {}).get('id')
                    if not user_id:
                        self.logger.error(f"User {username} not found")
                        return []

                # Get tweets with media
                timeline_url = f"https://api.twitter.com/2/users/{user_id}/tweets"
                params = {
                    'max_results': min(count, 100),
                    'expansions': 'attachments.media_keys',
                    'tweet.fields': 'attachments,created_at',
                    'media.fields': 'url,type,preview_image_url'
                }
                
                async with session.get(timeline_url, headers=headers, params=params) as response:
                    if response.status != 200:
                        self.logger.error(f"Error getting tweets: {response.status}")
                        return []
                    
                    data = await response.json()
                    
                    images = []
                    media_dict = {}
                    
                    # Build media lookup
                    for media in data.get('includes', {}).get('media', []):
                        if media.get('type') == 'photo' and media.get('url'):
                            media_dict[media['media_key']] = media['url']
                    
                    # Find tweets with images
                    for tweet in data.get('data', []):
                        attachments = tweet.get('attachments', {})
                        media_keys = attachments.get('media_keys', [])
                        for key in media_keys:
                            if key in media_dict:
                                images.append(media_dict[key])
                    
                    self.logger.info(f"API v2 fetched {len(images)} images for {username}")
                    return images
                    
        except Exception as e:
            self.logger.error(f"Error in Twitter API v2: {str(e)}")
            return []

    async def fetch_images_nitter(self, username: str, count: int = 20):
        """Use Nitter instance as fallback (unofficial, no API key needed)"""
        # Try different Nitter instances
        instances = [
            "https://nitter.net",
            "https://nitter.privacydev.net", 
            "https://nitter.poast.org",
            "https://nitter.fly.dev"
        ]
        
        for instance in instances:
            try:
                url = f"{instance}/{username}/media"
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers, timeout=10) as response:
                        if response.status == 200:
                            html = await response.text()
                            
                            # Simple parsing for image URLs in the HTML
                            import re
                            # Look for image URLs in the media page
                            pattern = r'https://pbs\.twimg\.com/media/[^\s"\']+'
                            images = re.findall(pattern, html)
                            
                            # Remove duplicates and return
                            unique_images = list(set(images))[:count]
                            if unique_images:
                                self.logger.info(f"Nitter fetched {len(unique_images)} images from {instance}")
                                return unique_images
                                
            except Exception as e:
                self.logger.debug(f"Nitter instance {instance} failed: {str(e)}")
                continue
                
        self.logger.warning(f"No Nitter instances worked for {username}")
        return []

    async def fetch_images_rss(self, username: str, count: int = 20):
        """Try RSS feed approach"""
        try:
            url = f"https://twitrss.me/twitter_user_to_rss/?user={username}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        text = await response.text()
                        
                        # Parse RSS for image links
                        import re
                        # Look for image URLs in the RSS content
                        images = re.findall(r'https://pbs\.twimg\.com/media/[^<"\']+', text)
                        unique_images = list(set(images))[:count]
                        
                        if unique_images:
                            self.logger.info(f"RSS fetched {len(unique_images)} images")
                            return unique_images
                            
        except Exception as e:
            self.logger.debug(f"RSS method failed: {str(e)}")
            
        return []

    async def fetch_images(self, username: str, count: int = 20):
        """Try multiple methods to fetch images"""
        self.logger.info(f"Attempting to fetch images for {username} using multiple methods...")
        
        # Method 1: Twitter API v2 (if configured)
        images = await self.fetch_images_v2(username, count)
        if images:
            return images
            
        # Method 2: Nitter fallback
        self.logger.info("Twitter API failed, trying Nitter...")
        images = await self.fetch_images_nitter(username, count)
        if images:
            return images
            
        # Method 3: RSS fallback  
        self.logger.info("Nitter failed, trying RSS...")
        images = await self.fetch_images_rss(username, count)
        if images:
            return images
            
        self.logger.error(f"All methods failed for {username}")
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
        
        # Try to immediately fetch images
        try:
            await ctx.send("🔄 Attempting to fetch images...")
            imgs = await self.fetch_images(username, 20)
            if imgs:
                await self.config.guild(ctx.guild).cached_images.set(imgs)
                await ctx.send(f"✅ Successfully cached {len(imgs)} images!")
            else:
                await ctx.send("❌ No images found using any method. The account might not exist or have no images.")
        except Exception as e:
            self.logger.error(f"Error in immediate fetch: {str(e)}")
            await ctx.send("❌ Error fetching images.")

    @commands.command(name="scran")
    async def scran(self, ctx):
        cached = await self.config.guild(ctx.guild).cached_images()
        username = await self.config.guild(ctx.guild).twitter_username()
        
        if not cached:
            self.logger.warning(f"Cache empty for {username} in guild {ctx.guild.id}")
            
            # Try to fetch immediately
            if username:
                await ctx.send("🔄 Cache empty, attempting to fetch images now...")
                imgs = await self.fetch_images(username, 20)
                if imgs:
                    await self.config.guild(ctx.guild).cached_images.set(imgs)
                    cached = imgs
                    await ctx.send(f"✅ Fetched {len(imgs)} images!")
                else:
                    return await ctx.send("❌ Could not fetch any images. The account might not exist or have no public images.")
            else:
                return await ctx.send("❌ No Twitter username set. Use `!twitterset username` first.")
        
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
                    imgs = await self.fetch_images(username, 20)
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
            
            self.last_run_time = time.time()
            cycle_duration = self.last_run_time - start_time
            
            self.logger.info(
                f"Scrape cycle completed: {guilds_processed} guilds processed, "
                f"{guilds_with_errors} guilds with errors, "
                f"{images_cached} total images cached, took {cycle_duration:.2f} seconds"
            )
            
            await asyncio.sleep(900)  # 15 minutes

    def cog_unload(self):
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
            imgs = await self.fetch_images(username, 20)
            if imgs:
                await self.config.guild(ctx.guild).cached_images.set(imgs)
                await ctx.send(f"✅ Successfully cached {len(imgs)} images!")
            else:
                await ctx.send("❌ No images found using any method.")
        except Exception as e:
            self.logger.error(f"Error in force_scrape: {str(e)}")
            await ctx.send("❌ Error fetching images.")

    @commands.command()
    @commands.admin_or_permissions(manage_guild=True) 
    async def twitter_debug(self, ctx):
        """Debug Twitter connection methods."""
        username = await self.config.guild(ctx.guild).twitter_username()
        if not username:
            return await ctx.send("No Twitter username set.")
            
        await ctx.send(f"🔍 Testing connection methods for `{username}`...")
        
        # Test each method
        methods = [
            ("Twitter API v2", self.fetch_images_v2),
            ("Nitter", self.fetch_images_nitter),
            ("RSS", self.fetch_images_rss)
        ]
        
        for method_name, method_func in methods:
            try:
                await ctx.send(f"Testing **{method_name}**...")
                images = await method_func(username, 5)
                if images:
                    await ctx.send(f"✅ {method_name}: Found {len(images)} images")
                    if len(images) > 0:
                        await ctx.send(f"Sample: {images[0]}")
                else:
                    await ctx.send(f"❌ {method_name}: No images found")
            except Exception as e:
                await ctx.send(f"❌ {method_name}: Error - {str(e)}")
            
            await asyncio.sleep(1)
