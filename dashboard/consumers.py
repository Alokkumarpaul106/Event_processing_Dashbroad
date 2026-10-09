import json
from channels.generic.websocket import AsyncWebsocketConsumer

class EventConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.room_group_name = "dashboard_events"

        # গ্রুপে জয়েন করা
        await self.channel_layer.group_add(
            self.room_group_name,
            self.channel_name
        )
        await self.accept()

    async def disconnect(self, close_code):
        # গ্রুপ থেকে বের হয়ে যাওয়া
        await self.channel_layer.group_discard(
            self.room_group_name,
            self.channel_name
        )

    # MQTT থেকে বা ব্যাকএন্ড থেকে ডেটা আসলে সেটি ক্লায়েন্টে পাঠানোর জন্য
    async def send_dashboard_event(self, event):
        data = event['data']
        await self.send(text_data=json.dumps(data))