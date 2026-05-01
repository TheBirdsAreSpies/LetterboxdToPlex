import { ref, computed, onBeforeUnmount } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js';

export function useTaskStream(onDataChanged) {
    const statusText = ref('');
    const statusLines = ref([]);
    const statusClass = ref('info');
    const statusVisible = ref(false);
    const actionInProgress = ref(false);

    const eventSource = ref(null);
    const maxLogLines = 50;

    const isLogView = computed(() => statusLines.value.length > 0);
    const formattedLog = computed(() => statusLines.value.join('<br>'));

    function clearLog() {
        statusLines.value = [];
    }

    function appendLog(line) {
        statusLines.value.push(line);
        if (statusLines.value.length > maxLogLines) {
            statusLines.value = statusLines.value.slice(statusLines.value.length - maxLogLines);
        }
    }

    function closeStream() {
        if (eventSource.value) {
            eventSource.value.close();
            eventSource.value = null;
        }
    }

    function startStream(taskName, replay) {
        closeStream();
        clearLog();
        statusVisible.value = true;
        statusClass.value = 'info';
        appendLog(`Streaming logs for ${taskName}...`);

        const replayFlag = replay ? '1' : '0';
        eventSource.value = new EventSource(`/stream/${taskName}?replay=${replayFlag}`);
        eventSource.value.onmessage = (event) => {
            appendLog(event.data);
        };
        eventSource.value.onerror = () => {
            appendLog('Stream ended or error occurred');
            closeStream();
            statusClass.value = 'success';
            actionInProgress.value = false;
            if (onDataChanged) {
                onDataChanged();
            }
        };
    }

    async function runAction(name) {
        statusVisible.value = true;
        statusClass.value = 'info';
        statusText.value = `Starting ${name}...`;
        clearLog();

        try {
            actionInProgress.value = true;

            if (name === 'owned') {
                const res = await fetch('/action/owned', { method: 'POST' });
                const blob = await res.blob();
                const url = window.URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'owned.csv';
                document.body.appendChild(a);
                a.click();
                a.remove();
                window.URL.revokeObjectURL(url);
                statusText.value = 'Owned CSV downloaded';
                statusClass.value = 'success';
                actionInProgress.value = false;
                return;
            }

            const res = await fetch(`/action/${name}`, { method: 'POST' });
            const data = await res.json();
            statusText.value = data.message || `${name} executed`;
            statusClass.value = data.success ? 'success' : 'error';

            if (data.success && (name === 'watchlist' || name === 'rating')) {
                startStream(name, false);
                return;
            }

            actionInProgress.value = false;
            if (onDataChanged) {
                await onDataChanged();
            }
        } catch (err) {
            statusText.value = `Error: ${err}`;
            statusClass.value = 'error';
            actionInProgress.value = false;
        }
    }

    async function reconnectRunningTask() {
        try {
            const res = await fetch('/task/status');
            const data = await res.json();
            const taskName = data.active_task;
            if (data.running && (taskName === 'watchlist' || taskName === 'rating')) {
                startStream(taskName, true);
            }
        } catch (err) {
            statusVisible.value = true;
            statusClass.value = 'error';
            statusText.value = `Error checking task status: ${err}`;
        }
    }

    onBeforeUnmount(() => {
        closeStream();
    });

    return {
        statusText,
        statusLines,
        statusClass,
        statusVisible,
        actionInProgress,
        isLogView,
        formattedLog,
        runAction,
        reconnectRunningTask
    };
}

