import discord
from redbot.core import commands, Config
import asyncio
import aiohttp
import random
import logging
import time
import re
import json

class InstagramImages(commands.Cog):
    """Pull latest images from an Instagram account."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=1234567892)
        default_guild = {"instagram_username": None, "cached_images": []}
        self.config.register_guild(**default_guild)
        
        self.logger = logging.getLogger('red.InstagramImages')
        self.last_run_time = None
        
        self.scrape_task = bot.loop.create_task(self.scrape_loop())

    async def fetch_images_instagram_api(self, username: str, count: int = 20):
        """Try to use Instagram's public data"""
        try:
            # Method 1: Try the public profile JSON endpoint
            url = f"https://www.instagram.com/api/v1/users/web_profile_info/?username={username}"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'X-IG-App-ID': '936619743392459'  # This is a public Instagram web app ID
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=10) as response:
                    if response.status == 200:
                        data = await response.json()
                        
                        images = []
                        user = data.get('data', {}).get('user', {})
                        posts = user.get('edge_owner_to_timeline_media', {}).get('edges', [])
                        
                        for post in posts:
                            node = post.get('node', {})
                            if node.get('is_video'):
                                continue  # Skip videos
                            
                            # Get the highest resolution image available
                            display_url = node.get('display_url')
                            if display_url:
                                images.append(display_url)
                            
                            if len(images) >= count:
                                break
                        
                        if images:
                            self.logger.info(f"Instagram API fetched {len(images)} images")
                            return images
                            
        except Exception as e:
            self.logger.debug(f"Instagram API method failed: {str(e)}")
            
        return []

    async def fetch_images_instagram_scraper(self, username: str, count: int = 20):
        """Scrape Instagram profile page directly"""
        try:
            url = f"https://www.instagram.com/{username}/"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
                'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                'Accept-Language': 'en-US,en;q=0.5',
            }
            
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=15) as response:
                    if response.status == 200:
                        html = await response.text()
                        
                        # Look for the shared data script tag
                        pattern = r'window\._sharedData\s*=\s*({.+?});'
                        match = re.search(pattern, html)
                        
                        if match:
                            shared_data = json.loads(match.group(1))
                            
                            # Navigate through the complex Instagram JSON structure
                            user_data = shared_data.get('entry_data', {}).get('ProfilePage', [{}])[0].get('graphql', {}).get('user', {})
                            posts = user_data.get('edge_owner_to_timeline_media', {}).get('edges', [])
                            
                            images = []
                            for post in posts:
                                node = post.get('node', {})
                                if node.get('is_video'):
                                    continue
                                
                                # Get display URL
                                display_url = node.get('display_url')
                                if display_url:
                                    images.append(display_url)
                                
                                if len(images) >= count:
                                    break
                            
                            if images:
                                self.logger.info(f"Instagram scraper found {len(images)} images")
                                return images
                        
                        # Fallback: Look for image URLs in HTML
                        image_urls = re.findall(r'https://instagram\.([^/]+)/p/[^\s"\']+', html)
                        if image_urls:
                            return list(set(image_urls))[:count]
                            
        except Exception as e:
            self.logger.debug(f"Instagram scraper failed: {str(e)}")
            
        return []

    async def fetch_images_instagram_rss(self, username: str, count: int = 20):
        """Use Instagram RSS services"""
        rss_services = [
            f"https://rsshub.app/instagram/user/{username}",
            f"https://insta.rss.today/{username}",
            f"https://www.instagramfeed.com/{username}/rss",
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
                            
                            # Look for image URLs in RSS
                            image_urls = re.findall(r'<media:content[^>]*url="([^"]+)"', text)
                            if not image_urls:
                                image_urls = re.findall(r'<img[^>]*src="([^"]+)"', text)
                            
                            if image_urls:
                                # Filter to Instagram CDN URLs
                                instagram_images = [url for url in image_urls if 'instagram.com' in url or 'cdninstagram.com' in url]
                                if instagram_images:
                                    return instagram_images[:count]
                                
            except Exception as e:
                self.logger.debug(f"RSS service {service_url} failed: {str(e)}")
                continue
                
        return []

    async def fetch_images_third_party(self, username: str, count: int = 20):
        """Use third-party Instagram viewers"""
        services = [
            f"https://imginn.com/{username}/",
            f"https://picuki.com/profile/{username}",
        ]
        
        for service_url in services:
            try:
                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
                }
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(service_url, headers=headers, timeout=10) as response:
                        if response.status == 200:
                            html = await response.text()
                            
                            # Look for image URLs in these services
                            image_urls = re.findall(r'https://[^"\']*\.(jpg|jpeg|png|webp)[^"\']*', html, re.IGNORECASE)
                            
                            # Filter to reasonable looking URLs (not icons, etc)
                            good_images = [url for url in image_urls if any(x in url for x in ['instagram', 'scontent', 'cdninstagram'])]
                            
                            if good_images:
                                return list(set(good_images))[:count]
                                
            except Exception as e:
                self.logger.debug(f"Third-party service {service_url} failed: {str(e)}")
                continue
                
        return []

    async def fetch_images(self, username: str, count: int = 20):
        """Try multiple methods to fetch Instagram images"""
        self.logger.info(f"Attempting to fetch Instagram images for {username}...")
        
        # Remove @ if present
        username = username.lstrip('@')
        
        methods = [
            ("Instagram API", self.fetch_images_instagram_api),
            ("Instagram Scraper", self.fetch_images_instagram_scraper),
            ("Instagram RSS", self.fetch_images_instagram_rss),
            ("Third-Party", self.fetch_images_third_party),
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
    async def instaset(self, ctx):
        """Instagram settings."""
        pass

    @instaset.command()
    async def username(self, ctx, username: str):
        # Remove @ if present
        username = username.lstrip('@')
        await self.config.guild(ctx.guild).instagram_username.set(username)
        await ctx.send(f"📸 Instagram username set to `{username}`.")
        self.logger.info(f"Instagram username set to {username} in guild {ctx.guild.id}")
        
        # Try to immediately fetch images
        try:
            await ctx.send("🔄 Attempting to fetch images from Instagram...")
            imgs = await self.fetch_images(username, 20)
            if imgs:
                await self.config.guild(ctx.guild).cached_images.set(imgs)
                await ctx.send(f"✅ Successfully cached {len(imgs)} images!")
                # Show a sample
                if len(imgs) > 0:
                    embed = discord.Embed(title="Sample Image", color=0xE1306C)
                    embed.set_image(url=imgs[0])
                    await ctx.send(embed=embed)
            else:
                await ctx.send("❌ No images found. The account might be private, have no posts, or all methods are currently blocked.")
        except Exception as e:
            self.logger.error(f"Error in immediate fetch: {str(e)}")
            await ctx.send("❌ Error fetching images.")

    @commands.command(name="scran")
    async def scran(self, ctx):
        """Get a random image from the cached Instagram posts"""
        cached = await self.config.guild(ctx.guild).cached_images()
        username = await self.config.guild(ctx.guild).instagram_username()
        
        if not cached:
            self.logger.warning(f"Cache empty for {username} in guild {ctx.guild.id}")
            
            if username:
                await ctx.send("🔄 Cache empty, attempting to fetch images from Instagram now...")
                imgs = await self.fetch_images(username, 20)
                if imgs:
                    await self.config.guild(ctx.guild).cached_images.set(imgs)
                    cached = imgs
                    await ctx.send(f"✅ Fetched {len(imgs)} images!")
                else:
                    return await ctx.send("❌ Could not fetch any images. The account might be private or have no posts.")
            else:
                return await ctx.send("❌ No Instagram username set. Use `!instaset username` first.")
        
        choice = random.choice(cached)
        embed = discord.Embed(color=0xE1306C)
        embed.set_image(url=choice)
        embed.set_footer(text=f"From @{username}" if username else "")
        await ctx.send(embed=embed)
        self.logger.debug(f"Sent random image from cache in guild {ctx.guild.id}")

    async def scrape_loop(self):
        await self.bot.wait_until_ready()
        self.logger.info("InstagramImages scraper loop started")
        
        while True:
            start_time = time.time()
            self.logger.info("Starting Instagram scrape cycle")
            
            guilds_processed = 0
            images_cached = 0
            guilds_with_errors = 0

            for guild in self.bot.guilds:
                username = await self.config.guild(guild).instagram_username()
                if not username:
                    continue
                    
                try:
                    self.logger.debug(f"Scraping Instagram images for {username} in guild {guild.id}")
                    imgs = await self.fetch_images(username, 20)
                    if imgs:
                        await self.config.guild(guild).cached_images.set(imgs)
                        guilds_processed += 1
                        images_cached += len(imgs)
                        self.logger.info(f"Cached {len(imgs)} Instagram images for {username} in guild {guild.id}")
                    else:
                        self.logger.warning(f"No Instagram images found for {username} in guild {guild.id}")
                        guilds_with_errors += 1
                except Exception as e:
                    self.logger.error(f"Error scraping Instagram for {username} in guild {guild.id}: {str(e)}")
                    guilds_with_errors += 1
            
            self.last_run_time = time.time()
            cycle_duration = self.last_run_time - start_time
            
            self.logger.info(
                f"Instagram scrape cycle completed: {guilds_processed} guilds processed, "
                f"{guilds_with_errors} guilds with errors, "
                f"{images_cached} total images cached, took {cycle_duration:.2f} seconds"
            )
            
            await asyncio.sleep(1800)  # 30 minutes (Instagram is less rate-limited than Twitter)

    def cog_unload(self):
        if self.scrape_task:
            self.scrape_task.cancel()
        self.logger.info("InstagramImages scraper loop stopped")

    @commands.command()
    @commands.admin_or_permissions(manage_guild=True)
    async def insta_force(self, ctx):
        """Force an immediate scrape for this server's Instagram username."""
        username = await self.config.guild(ctx.guild).instagram_username()
        if not username:
            return await ctx.send("❌ No Instagram username set for this server.")
        
        await ctx.send(f"🔄 Force scraping Instagram images for `{username}`...")
        
        try:
            imgs = await self.fetch_images(username, 20)
            if imgs:
                await self.config.guild(ctx.guild).cached_images.set(imgs)
                await ctx.send(f"✅ Successfully cached {len(imgs)} images!")
            else:
                await ctx.send("❌ No images found using any method.")
        except Exception as e:
            self.logger.error(f"Error in insta_force: {str(e)}")
            await ctx.send("❌ Error fetching images.")

    @commands.command()
    @commands.admin_or_permissions(manage_guild=True) 
    async def insta_debug(self, ctx):
        """Debug Instagram connection methods."""
        username = await self.config.guild(ctx.guild).instagram_username()
        if not username:
            return await ctx.send("❌ No Instagram username set.")
            
        await ctx.send(f"🔍 Testing Instagram connection methods for `{username}`...")
        
        methods = [
            ("Instagram API", self.fetch_images_instagram_api),
            ("Instagram Scraper", self.fetch_images_instagram_scraper),
            ("Instagram RSS", self.fetch_images_instagram_rss),
            ("Third-Party", self.fetch_images_third_party),
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
        embed = discord.Embed(title="Instagram Debug Results", description=summary, color=0xE1306C)
        await ctx.send(embed=embed)

    @commands.command()
    async def insta_status(self, ctx):
        """Check current Instagram image status."""
        username = await self.config.guild(ctx.guild).instagram_username()
        cached = await self.config.guild(ctx.guild).cached_images()
        
        if not username:
            return await ctx.send("❌ No Instagram username set.")
        
        embed = discord.Embed(title="📸 Instagram Status", color=0xE1306C)
        embed.add_field(name="Username", value=f"@{username}", inline=True)
        embed.add_field(name="Cached Images", value=len(cached) if cached else "0", inline=True)
        embed.add_field(name="Last Scrape", value=f"<t:{int(self.last_run_time or time.time())}:R>" if self.last_run_time else "Never", inline=True)
        
        if cached:
            embed.add_field(name="Sample Image", value=f"[View]({cached[0]})", inline=True)
        
        await ctx.send(embed=embed)

    @commands.command()
    async def insta_refresh(self, ctx):
        """Manually refresh the Instagram cache."""
        username = await self.config.guild(ctx.guild).instagram_username()
        if not username:
            return await ctx.send("❌ No Instagram username set.")
            
        await ctx.send(f"🔄 Refreshing Instagram cache for @{username}...")
        
        old_count = len(await self.config.guild(ctx.guild).cached_images())
        imgs = await self.fetch_images(username, 20)
        
        if imgs:
            await self.config.guild(ctx.guild).cached_images.set(imgs)
            embed = discord.Embed(
                title="✅ Cache Refreshed", 
                description=f"Updated from {old_count} to {len(imgs)} images", 
                color=0xE1306C
            )
            await ctx.send(embed=embed)
        else:
            await ctx.send("❌ Failed to refresh cache. No images found.")
