import discord
from redbot.core import commands, Config
import asyncio
import aiohttp
import random
import logging
import time
import re

class TwitterImages(commands.Cog):
    """Pull latest images from a Twitter account."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567890)
        default_guild = {"twitter_username": None, "cached_images": []}
        self.config.register_guild(**default_guild)
        
        self.logger = logging.getLogger('red.TwitterImages')
        self.last_run_time = None
        
        self.scrape_task = bot.loop.create_task(self.scrape_loop())

    async def fetch_images_direct_embed(self, username: str, count: int = 20):
        """Try to extract images from Twitter embed API"""
        try:
            # Use Twitter's oEmbed API which sometimes works without authentication
            embed_url = f"https://publish.twitter.com/oembed?url=https://twitter.com/{username}&omit_script=1"
            
            async with aiohttp.ClientSession() as session:
                async with session.get(embed_url, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        html = data.get('html', '')
                        
                        # Extract image URLs from the HTML
                        image_urls = re.findall(r'https://pbs\.twimg\.com/media/[^\s"\']+', html)
                        if image_urls:
                            return list(set(image_urls))[:count]
            
            # Try mobile Twitter
            mobile_url = f"https://mobile.twitter.com/{username}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 14_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1'
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(mobile_url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        html = await response.text()
                        # Look for image patterns in mobile site
                        image_urls = re.findall(r'https://pbs\.twimg\.com/media/[^\s"\']+', html)
                        image_urls.extend(re.findall(r'https://pbs\.twimg\.com/profile_images/[^\s"\']+', html))
                        image_urls.extend(re.findall(r'https://pbs\.twimg\.com/ext_tw_video_thumb/[^\s"\']+', html))
                        
                        if image_urls:
                            return list(set(image_urls))[:count]
                            
        except Exception as e:
            self.logger.debug(f"Direct embed method failed: {str(e)}")
            
        return []

    async def fetch_images_twitter_api_guest(self, username: str, count: int = 20):
        """Try to use Twitter's guest token API"""
        try:
            # First get a guest token
            async with aiohttp.ClientSession() as session:
                # Get guest token
                async with session.post('https://api.twitter.com/1.1/guest/activate.json', 
                                      headers={'Authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA'}) as response:
                    if response.status == 200:
                        token_data = await response.json()
                        guest_token = token_data.get('guest_token')
                        
                        if guest_token:
                            # Use the guest token to fetch user timeline
                            timeline_url = f"https://api.twitter.com/2/timeline/profile/{username}.json"
                            params = {
                                'count': count,
                                'include_entities': 1
                            }
                            headers = {
                                'Authorization': 'Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA',
                                'x-guest-token': guest_token
                            }
                            
                            async with session.get(timeline_url, headers=headers, params=params, timeout=10) as response:
                                if response.status == 200:
                                    data = await response.json()
                                    images = []
                                    
                                    # Parse the complex Twitter response
                                    tweets = data.get('globalObjects', {}).get('tweets', {})
                                    for tweet_id, tweet in tweets.items():
                                        entities = tweet.get('entities', {})
                                        media_list = entities.get('media', [])
                                        for media in media_list:
                                            if media.get('type') == 'photo':
                                                images.append(media.get('media_url_https'))
                                    
                                    if images:
                                        return images[:count]
                                        
        except Exception as e:
            self.logger.debug(f"Twitter guest API failed: {str(e)}")
            
        return []

    async def fetch_images_alternative_rss(self, username: str, count: int = 20):
        """Try alternative RSS services"""
        rss_services = [
            f"https://twiiit.com/rss/{username}",
            f"https://rss.app/twitter-user/{username}",
            f"https://api.rss2json.com/v1/api.json?rss_url=https://twitrss.me/twitter_user_to_rss/?user={username}",
        ]
        
        for service_url in rss_services:
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(service_url, headers=headers, timeout=10) as response:
                        if response.status == 200:
                            text = await response.text()
                            # Look for Twitter image URLs
                            image_urls = re.findall(r'https://pbs\.twimg\.com/media/[^\s"\']+', text)
                            if image_urls:
                                return list(set(image_urls))[:count]
                                
            except Exception as e:
                self.logger.debug(f"RSS service {service_url} failed: {str(e)}")
                continue
                
        return []

    async def fetch_images_web_scraping(self, username: str, count: int = 20):
        """Try direct web scraping of Twitter profile"""
        try:
            url = f"https://twitter.com/{username}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=15) as response:
                    if response.status == 200:
                        html = await response.text()
                        
                        # Try to find images in the HTML
                        image_urls = []
                        
                        # Look for various Twitter image patterns
                        patterns = [
                            r'https://pbs\.twimg\.com/media/[^\s"\']+',
                            r'https://pbs\.twimg\.com/profile_images/[^\s"\']+',
                            r'https://pbs\.twimg\.com/ext_tw_video_thumb/[^\s"\']+',
                            r'https://pbs\.twimg\.com/amplify_video_thumb/[^\s"\']+',
                        ]
                        
                        for pattern in patterns:
                            found = re.findall(pattern, html)
                            image_urls.extend(found)
                        
                        if image_urls:
                            unique_images = list(set(image_urls))
                            self.logger.info(f"Web scraping found {len(unique_images)} images")
                            return unique_images[:count]
                            
        except Exception as e:
            self.logger.debug(f"Web scraping failed: {str(e)}")
            
        return []

    async def fetch_images(self, username: str, count: int = 20):
        """Try ALL methods to fetch images"""
        self.logger.info(f"Attempting to fetch images for {username} using ALL methods...")
        
        methods = [
            ("Web Scraping", self.fetch_images_web_scraping),
            ("Direct Embed", self.fetch_images_direct_embed),
            ("Twitter Guest API", self.fetch_images_twitter_api_guest),
            ("Alternative RSS", self.fetch_images_alternative_rss),
        ]
        
        for method_name, method_func in methods:
            try:
                self.logger.info(f"Trying {method_name}...")
                images = await method_func(username, count)
                if images:
                    self.logger.info(f"✅ {method_name} succeeded with {len(images)} images")
                    return images
                else:
                    self.logger.info(f"❌ {method_name} found no images")
            except Exception as e:
                self.logger.warning(f"Method {method_name} failed: {str(e)}")
            
            await asyncio.sleep(1)  # Brief pause between methods
        
        self.logger.error(f"All methods failed for {username}")
        return []

    @commands.group()
    @commands.admin_or_permissions(manage_guild=True)
    async def twitterset(self, ctx):
        """Twitter settings."""
        pass

    @twitterset.command()
    async def username(self, ctx, username: str):
        # Remove @ if present
        username = username.lstrip('@')
        await self.config.guild(ctx.guild).twitter_username.set(username)
        await ctx.send(f"Twitter username set to `{username}`.")
        self.logger.info(f"Twitter username set to {username} in guild {ctx.guild.id}")
        
        # Try to immediately fetch images
        try:
            await ctx.send("🔄 Attempting to fetch images using multiple methods...")
            imgs = await self.fetch_images(username, 20)
            if imgs:
                await self.config.guild(ctx.guild).cached_images.set(imgs)
                await ctx.send(f"✅ Successfully cached {len(imgs)} images!")
                # Show a sample
                if len(imgs) > 0:
                    embed = discord.Embed(title="Sample Image")
                    embed.set_image(url=imgs[0])
                    await ctx.send(embed=embed)
            else:
                await ctx.send("❌ No images found using any method. The account might be private, have no images, or all methods are currently blocked.")
        except Exception as e:
            self.logger.error(f"Error in immediate fetch: {str(e)}")
            await ctx.send("❌ Error fetching images.")

    @commands.command(name="scran")
    async def scran(self, ctx):
        cached = await self.config.guild(ctx.guild).cached_images()
        username = await self.config.guild(ctx.guild).twitter_username()
        
        if not cached:
            self.logger.warning(f"Cache empty for {username} in guild {ctx.guild.id}")
            
            if username:
                await ctx.send("🔄 Cache empty, attempting to fetch images now...")
                imgs = await self.fetch_images(username, 20)
                if imgs:
                    await self.config.guild(ctx.guild).cached_images.set(imgs)
                    cached = imgs
                    await ctx.send(f"✅ Fetched {len(imgs)} images!")
                else:
                    return await ctx.send("❌ Could not fetch any images. The account might be private or have restrictions.")
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
            
        await ctx.send(f"🔍 Testing ALL connection methods for `{username}`...")
        
        methods = [
            ("Web Scraping", self.fetch_images_web_scraping),
            ("Direct Embed", self.fetch_images_direct_embed),
            ("Twitter Guest API", self.fetch_images_twitter_api_guest),
            ("Alternative RSS", self.fetch_images_alternative_rss),
        ]
        
        results = []
        
        for method_name, method_func in methods:
            try:
                await ctx.send(f"Testing **{method_name}**...")
                images = await method_func(username, 5)
                if images:
                    result = f"✅ {method_name}: Found {len(images)} images"
                    if len(images) > 0:
                        result += f"\nSample: {images[0][:50]}..."
                    results.append(result)
                else:
                    results.append(f"❌ {method_name}: No images found")
            except Exception as e:
                results.append(f"❌ {method_name}: Error - {str(e)}")
            
            await asyncio.sleep(1)
        
        # Send summary
        summary = "\n".join(results)
        await ctx.send(f"**Debug Results:**\n{summary}")

    @commands.command()
    async def twitter_status(self, ctx):
        """Check current Twitter image status."""
        username = await self.config.guild(ctx.guild).twitter_username()
        cached = await self.config.guild(ctx.guild).cached_images()
        
        if not username:
            return await ctx.send("No Twitter username set.")
        
        embed = discord.Embed(title="Twitter Image Status", color=0x1DA1F2)
        embed.add_field(name="Username", value=username, inline=True)
        embed.add_field(name="Cached Images", value=len(cached) if cached else "0", inline=True)
        embed.add_field(name="Last Scrape", value=f"<t:{int(self.last_run_time or time.time())}:R>" if self.last_run_time else "Never", inline=True)
        
        if cached:
            embed.add_field(name="Sample Image", value=f"[View]({cached[0]})", inline=True)
        
        await ctx.send(embed=embed)
