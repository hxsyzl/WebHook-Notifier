document.addEventListener('DOMContentLoaded', () => {
    const webhookUrlInput = document.getElementById('webhook-url');
    const payloadTextarea = document.getElementById('payload');
    const sendBtn = document.getElementById('send-btn');
    const responsePre = document.getElementById('response');

    sendBtn.addEventListener('click', async () => {
        const url = webhookUrlInput.value.trim();
        const payloadString = payloadTextarea.value.trim();

        if (!url) {
            alert('请输入 WebHook URL。');
            return;
        }

        if (!payloadString) {
            alert('请输入 JSON Payload。');
            return;
        }

        let payload;
        try {
            payload = JSON.parse(payloadString);
        } catch (error) {
            alert('JSON Payload 格式无效，请检查。\n错误: ' + error.message);
            return;
        }

        responsePre.textContent = '正在发送请求...';
        sendBtn.disabled = true;
        sendBtn.textContent = '发送中...';

        try {
            const response = await fetch(url, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify(payload)
            });

            const responseData = await response.text();
            let formattedData;
            try {
                // 尝试格式化为JSON
                formattedData = JSON.stringify(JSON.parse(responseData), null, 2);
            } catch (e) {
                // 如果不是有效的JSON，则直接显示文本
                formattedData = responseData;
            }
            
            responsePre.textContent = `状态码: ${response.status}\n\n${formattedData}`;

        } catch (error) {
            responsePre.textContent = '请求失败:\n' + error.message;
        } finally {
            sendBtn.disabled = false;
            sendBtn.textContent = '发送 WebHook';
        }
    });
});
