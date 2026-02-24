class ConsoleOutput:
    def __init__(self, show_album=True):
        self.show_album = show_album

    async def on_track(self, event):
        line = f"🎵 {event['author']} — {event['name']}"
        if self.show_album and event.get("album"):
            line += f" [{event['album']}]"
        print(line)

    async def on_volume(self, event):
        print(f"🔊 Громкость: {event['value']}%")
    
    async def on_load(self, event):
        print("⚠️ РЕЗКИЙ РОСТ НАГРУЗКИ СИСТЕМЫ:")
        print(f"CPU: {event['cpu']:.1f}%")
        print(f"RAM: {event['ram']:.1f}%")
        print(f"GPU: {event['gpu']:.1f}%")
        print("-" * 30)
