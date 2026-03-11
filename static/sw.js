// Service Worker - プッシュ通知受信
self.addEventListener("push", function(event) {
    let data = { title: "🔔 呼び出し", body: "受付カウンターへお越しください" };
    try {
        data = JSON.parse(event.data.text());
    } catch(e) {}

    event.waitUntil(
        self.registration.showNotification(data.title, {
            body: data.body,
            icon: "/static/icon.png",
            badge: "/static/icon.png",
            vibrate: [200, 100, 200, 100, 200],
            requireInteraction: true,  // 手動で閉じるまで残る
            tag: "call-notification",
        })
    );
});

self.addEventListener("notificationclick", function(event) {
    event.notification.close();
    event.waitUntil(
        clients.openWindow("/status")
    );
});
