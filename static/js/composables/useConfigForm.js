import { ref, reactive } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js';

export function useConfigForm(sections) {
    const enumValues = [
        'ReleaseType.PREMIERE',
        'ReleaseType.THEATRICAL_LIMITED',
        'ReleaseType.THEATRICAL',
        'ReleaseType.DIGITAL',
        'ReleaseType.PHYSICAL',
        'ReleaseType.TV'
    ];

    const originalConfig = ref({});
    const formValues = ref({});
    const sectionState = reactive({});
    const status = reactive({
        visible: false,
        success: false,
        message: ''
    });

    async function loadConfig() {
        const res = await fetch('/config/data');
        const cfg = await res.json();
        originalConfig.value = cfg;

        const values = {};
        Object.keys(cfg).forEach((key) => {
            const value = cfg[key];
            if (Array.isArray(value)) {
                values[key] = value.join(', ');
            } else {
                values[key] = value;
            }
        });
        formValues.value = values;

        Object.keys(sectionState).forEach((key) => {
            delete sectionState[key];
        });
        Object.keys(sections).forEach((sectionName) => {
            sectionState[sectionName] = true;
        });
    }

    function hasKey(key) {
        return Object.prototype.hasOwnProperty.call(formValues.value, key);
    }

    function fieldType(key) {
        if (key === 'tmdb_release_type') {
            return 'enum';
        }

        const original = originalConfig.value[key];
        if (typeof original === 'boolean') {
            return 'boolean';
        }
        if (Array.isArray(original)) {
            return 'array';
        }
        return 'text';
    }

    function enumLabel(value) {
        return value.split('.')[1] || value;
    }

    function normalizeArrayText(text) {
        return String(text)
            .split(',')
            .map((v) => v.trim())
            .filter((v) => v.length > 0);
    }

    function isChanged(key) {
        const original = originalConfig.value[key];
        const current = formValues.value[key];

        if (Array.isArray(original)) {
            const left = original.join(',');
            const right = normalizeArrayText(current).join(',');
            return left !== right;
        }

        return current !== original;
    }

    function isOpen(sectionName) {
        return !!sectionState[sectionName];
    }

    function toggleSection(sectionName) {
        sectionState[sectionName] = !sectionState[sectionName];
    }

    function goBack() {
        window.location.href = '/';
    }

    async function saveConfig() {
        const payload = {};
        Object.entries(sections).forEach(([, keys]) => {
            keys.forEach((key) => {
                if (!hasKey(key)) {
                    return;
                }

                const t = fieldType(key);
                if (t === 'array') {
                    payload[key] = normalizeArrayText(formValues.value[key]);
                } else {
                    payload[key] = formValues.value[key];
                }
            });
        });

        if (payload.tmdb_release_type) {
            const enumPart = String(payload.tmdb_release_type).split('.')[1];
            payload.tmdb_release_type = `ReleaseType.${enumPart}`;
        }

        const res = await fetch('/config/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });

        const result = await res.json();
        status.visible = true;
        status.success = !!result.success;
        status.message = result.message || 'Finished';

        if (result.success) {
            await loadConfig();
        }
    }

    return {
        enumValues,
        formValues,
        status,
        loadConfig,
        hasKey,
        fieldType,
        enumLabel,
        isChanged,
        isOpen,
        toggleSection,
        goBack,
        saveConfig
    };
}

