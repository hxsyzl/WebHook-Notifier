document.addEventListener('DOMContentLoaded', function() {
    const form = document.getElementById('webhook-form');
    const responseContainer = document.getElementById('response');
    const responseContent = document.getElementById('response-content');

    form.addEventListener('submit', async function(e) {
        e.preventDefault();
        
        const url = document.getElementById('url').value;
        const method = document.getElementById('method').value;
        const headersInput = document.getElementById('headers').value;
        const payloadInput = document.getElementById('payload').value;
        
        let headers = {};
        try {
            if (headersInput.trim()) {
                headers = JSON.parse(headersInput);
            }
        } catch (e) {
            showError('请求头格式错误，请确保是有效的 JSON 格式');
            return;
        }
        
        let payload = null;
        try {
            if (payloadInput.trim()) {
                payload = JSON.parse(payloadInput);
            }
        } catch (e) {
            showError('Payload 格式错误，请确保是有效的 JSON 格式');
            return;
        }
        
        // 如果是 POST/PUT 方法且没有设置 Content-Type，则默认设置为 application/json
        if ((method === 'POST' || method === 'PUT') && !headers['Content-Type']) {
            headers['Content-Type'] = 'application/json';
        }
        
        try {
            const response = await sendWebhook(url, method, headers, payload);
            showResponse(response);
        } catch (error) {
            showError(`请求失败: ${error.message}`);
        }
    });
    
    function sendWebhook(url, method, headers, payload) {
        const options = {
            method: method,
            headers: headers
        };
        
        if (payload && (method === 'POST' || method === 'PUT')) {
            options.body = JSON.stringify(payload);
        }
        
        return fetch(url, options)
            .then(response => {
                return response.text().then(text => {
                    return {
                        status: response.status,
                        statusText: response.statusText,
                        headers: [...response.headers.entries()],
                        body: text
                    };
                });
            });
    }
    
    function showResponse(response) {
        responseContainer.style.display = 'block';
        responseContent.textContent = JSON.stringify(response, null, 2);
        responseContent.style.color = 'white';
    }
    
    function showError(message) {
        responseContainer.style.display = 'block';
        responseContent.textContent = message;
        responseContent.style.color = 'red';
    }
});