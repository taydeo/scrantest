from .instaimages import InstagramImages

async def setup(bot):
    cog = InstagramImages(bot)
    await bot.add_cog(cog)
