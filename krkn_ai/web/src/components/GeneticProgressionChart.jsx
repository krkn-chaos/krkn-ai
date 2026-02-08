import React from 'react';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend } from 'recharts';
import { motion } from 'framer-motion';

const GeneticProgressionChart = ({ data }) => {
    return (
        <motion.div
            initial={{ opacity: 0, scale: 0.95 }}
            animate={{ opacity: 1, scale: 1 }}
            className="p-6 rounded-xl border border-border bg-card h-[400px] w-full"
        >
            <h3 className="text-lg font-semibold mb-6">Genetic Progression</h3>
            <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data} margin={{ top: 5, right: 30, left: 20, bottom: 25 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#2a2a2a" />
                    <XAxis
                        dataKey="generation"
                        label={{ value: 'Generation', position: 'bottom', offset: 0 }}
                        stroke="#888"
                    />
                    <YAxis
                        label={{ value: 'Fitness Score', angle: -90, position: 'insideLeft' }}
                        stroke="#888"
                    />
                    <Tooltip
                        contentStyle={{ backgroundColor: '#1a1a1a', border: '1px solid #333', borderRadius: '8px' }}
                        itemStyle={{ fontSize: '12px' }}
                    />
                    <Legend wrapperStyle={{ paddingTop: '10px' }} />
                    <Line
                        type="monotone"
                        dataKey="best"
                        name="Best Fitness"
                        stroke="#3b82f6"
                        strokeWidth={3}
                        dot={{ r: 6 }}
                        activeDot={{ r: 8 }}
                    />
                    <Line
                        type="monotone"
                        dataKey="average"
                        name="Average Fitness"
                        stroke="#8b5cf6"
                        strokeWidth={2}
                        strokeDasharray="5 5"
                    />
                </LineChart>
            </ResponsiveContainer>
        </motion.div>
    );
};

export default GeneticProgressionChart;
