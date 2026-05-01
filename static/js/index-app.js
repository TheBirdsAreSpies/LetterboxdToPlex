import { createApp, ref, computed, onMounted, onBeforeUnmount } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js';
import { useTaskStream } from './composables/useTaskStream.js';

const app = createApp({
    setup() {
        const missing = ref([]);
        const autoselections = ref([]);
        const sortBy = ref('name');
        const sortDirection = ref('asc');
        const autoSelectionPollId = ref(null);

        async function loadMissing() {
            const res = await fetch('/missing');
            missing.value = await res.json();
        }

        async function loadAutoselections() {
            const res = await fetch('/autoselections');
            autoselections.value = await res.json();
        }

        function sortValue(item, field) {
            if (field === 'release_date') {
                const raw = item.release_date;
                if (!raw) {
                    return Number.POSITIVE_INFINITY;
                }
                const parsed = Date.parse(raw);
                return Number.isNaN(parsed) ? Number.POSITIVE_INFINITY : parsed;
            }

            if (field === 'year') {
                const n = Number(item.year);
                return Number.isNaN(n) ? Number.POSITIVE_INFINITY : n;
            }

            return String(item.name || '').toLowerCase();
        }

        const sortedMissing = computed(() => {
            const items = [...missing.value];
            const dir = sortDirection.value === 'asc' ? 1 : -1;
            items.sort((a, b) => {
                const aVal = sortValue(a, sortBy.value);
                const bVal = sortValue(b, sortBy.value);
                if (aVal < bVal) {
                    return -1 * dir;
                }
                if (aVal > bVal) {
                    return 1 * dir;
                }
                return 0;
            });
            return items;
        });

        function setSort(field) {
            if (sortBy.value === field) {
                sortDirection.value = sortDirection.value === 'asc' ? 'desc' : 'asc';
                return;
            }
            sortBy.value = field;
            sortDirection.value = 'asc';
        }

        function sortIndicator(field) {
            if (sortBy.value !== field) {
                return '▲▼';
            }
            return sortDirection.value === 'asc' ? '▲' : '▼';
        }

        function formatReleaseDate(value) {
            if (!value) {
                return '-';
            }
            return String(value).split('T')[0].split(' ')[0];
        }

        function optionLabel(opt) {
            return `${opt.title} (${opt.year})${opt.edition ? ' - ' + opt.edition : ''}`;
        }

        async function ignoreItem(name) {
            const confirmed = window.confirm(`Do you really want to add "${name}" to ignore list?`);
            if (!confirmed) {
                return;
            }

            const res = await fetch('/ignore', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name })
            });

            if (res.ok) {
                await loadMissing();
            }
        }

        async function chooseAutoselection(sel, opt) {
            await fetch('/autoselections/choose', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: sel.combination.name,
                    year: sel.combination.year,
                    selected_key: opt.key
                })
            });
            await loadAutoselections();
        }

        async function skipAutoselection(sel) {
            await fetch('/autoselections/skip', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    name: sel.combination.name,
                    year: sel.combination.year
                })
            });
            await loadAutoselections();
        }

        const taskStream = useTaskStream(loadMissing);

        onMounted(async () => {
            await loadMissing();
            await loadAutoselections();
            await taskStream.reconnectRunningTask();
            autoSelectionPollId.value = window.setInterval(() => {
                loadAutoselections();
            }, 5000);
        });

        onBeforeUnmount(() => {
            if (autoSelectionPollId.value) {
                window.clearInterval(autoSelectionPollId.value);
            }
        });

        return {
            missing,
            autoselections,
            sortBy,
            sortDirection,
            sortedMissing,
            setSort,
            sortIndicator,
            formatReleaseDate,
            optionLabel,
            ignoreItem,
            chooseAutoselection,
            skipAutoselection,
            ...taskStream
        };
    }
});

app.config.compilerOptions.delimiters = ['[[', ']]'];
app.mount('#app');

