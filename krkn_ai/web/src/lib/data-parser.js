/**
 * Data parsing utilities for Krkn-AI results
 */

// Extract security token from URL parameters
const getSecurityToken = () => {
    const params = new URLSearchParams(window.location.search);
    return params.get('token') || '';
};

export const parseResults = async (url = '/results.json') => {
    try {
        const token = getSecurityToken();
        const urlWithToken = token ? `${url}?token=${encodeURIComponent(token)}` : url;
        const response = await fetch(urlWithToken);
        if (!response.ok) throw new Error('Failed to fetch results');
        return await response.json();
    } catch (err) {
        console.error('Error parsing results.json:', err);
        return null;
    }
};

export const parseCSV = (csvText) => {
    if (!csvText) return [];
    const lines = csvText.split('\n').filter(line => line.trim());
    if (lines.length === 0) return [];

    // Robust CSV split function that handles quoted commas
    const splitCSVLine = (line) => {
        const matches = line.matchAll(/("([^"]*)"|[^,]+|(?<=,)(?=,)|(?<=^)(?=,)|(?<=,)(?=$))/g);
        return Array.from(matches).map(m => {
            let val = m[0];
            if (val.startsWith('"') && val.endsWith('"')) {
                val = val.substring(1, val.length - 1);
            }
            return val;
        });
    };

    const headers = splitCSVLine(lines[0]);
    return lines.slice(1).map(line => {
        const values = splitCSVLine(line);
        return headers.reduce((obj, header, i) => {
            if (!header) return obj;
            let val = values[i] !== undefined ? values[i] : "";
            // Try to parse numbers
            const trimmedVal = val.toString().trim();
            if (!isNaN(trimmedVal) && trimmedVal !== '') {
                val = parseFloat(trimmedVal);
            }
            obj[header.trim()] = val;
            return obj;
        }, {});
    });
};

export const loadAllData = async (baseUrl = '') => {
    const token = getSecurityToken();
    const tokenParam = token ? `?token=${encodeURIComponent(token)}` : '';

    const [results, csvText] = await Promise.all([
        parseResults(`${baseUrl}/results.json`),
        fetch(`${baseUrl}/reports/all.csv${tokenParam}`).then(res => res.ok ? res.text() : '').catch(() => '')
    ]);

    const scenarios = parseCSV(csvText);

    return {
        results,
        scenarios,
        isLoaded: !!results
    };
};
