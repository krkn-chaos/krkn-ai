/**
 * Data parsing utilities for Krkn-AI results
 */

export const parseResults = async (url = '/results.json') => {
    try {
        const response = await fetch(url);
        if (!response.ok) throw new Error('Failed to fetch results');
        return await response.json();
    } catch (err) {
        console.error('Error parsing results.json:', err);
        return null;
    }
};

export const parseCSV = (csvText) => {
    if (!csvText) return [];
    const lines = csvText.split('\n');
    if (lines.length === 0) return [];

    const headers = lines[0].split(',');
    return lines.slice(1).filter(line => line.trim()).map(line => {
        const values = line.split(',');
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
    const [results, csvText] = await Promise.all([
        parseResults(`${baseUrl}/results.json`),
        fetch(`${baseUrl}/reports/all.csv`).then(res => res.ok ? res.text() : '').catch(() => '')
    ]);

    const scenarios = parseCSV(csvText);

    return {
        results,
        scenarios,
        isLoaded: !!results
    };
};
