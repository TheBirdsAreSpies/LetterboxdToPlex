import { createApp, onMounted } from 'https://unpkg.com/vue@3/dist/vue.esm-browser.prod.js';
import { useConfigForm } from './composables/useConfigForm.js';

const sections = {
    'plex settings': ['baseurl', 'token'],
    'letterboxd settings': ['use_api', 'api_username', 'api_password', 'api_use_2fa_code'],
    'general settings': [
        'use_playlist_as_watchlist',
        'use_builtin_watchlist',
        'sort_by_title',
        'ignore_words',
        'ignore_movies_in_existing_watchlist',
        'include_watched_not_rated'
    ],
    'plex watchlist as playlist settings': ['existing_watchlist_name', 'watchlist_name_to_create'],
    'tmdb': [
        'tmdb_use_api',
        'tmdb_cache',
        'tmdb_invalidate_cache',
        'tmdb_invalidate_cache_days',
        'tmdb_api_key',
        'tmdb_language_code',
        'tmdb_release_country_code',
        'tmdb_release_type'
    ],
    'existing files': ['watchlist_path', 'watched_path', 'ratings_path'],
    'files to create': ['missing_path', 'ignore_path', 'mapping_path', 'autoselection_path']
};

const app = createApp({
    setup() {
        const form = useConfigForm(sections);

        onMounted(() => {
            form.loadConfig();
        });

        return {
            sections,
            ...form
        };
    }
});

app.config.compilerOptions.delimiters = ['[[', ']]'];
app.mount('#app');

