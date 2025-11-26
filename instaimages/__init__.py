from .twitterimages import TwitterImages

async def setup(bot):
    await bot.add_cog(TwitterImages(bot))
