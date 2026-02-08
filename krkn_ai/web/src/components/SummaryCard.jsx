import React from 'react';
import { motion } from 'framer-motion';

const SummaryCard = ({ title, value, icon: Icon, trend, color = 'blue' }) => {
    const colorMap = {
        blue: 'text-blue-500 bg-blue-500/10',
        green: 'text-green-500 bg-green-500/10',
        purple: 'text-purple-500 bg-purple-500/10',
        red: 'text-red-500 bg-red-500/10',
        yellow: 'text-yellow-500 bg-yellow-500/10',
    };

    return (
        <motion.div
            initial={{ opacity: 0, y: 10 }}
            animate={{ opacity: 1, y: 0 }}
            className="p-6 rounded-xl border border-border bg-card text-card-foreground shadow-sm hover:border-accent transition-colors"
        >
            <div className="flex justify-between items-start">
                <div>
                    <p className="text-sm font-medium text-muted-foreground">{title}</p>
                    <h3 className="text-2xl font-bold mt-1">{value}</h3>
                    {trend && (
                        <p className={`text-xs mt-1 ${trend > 0 ? 'text-green-500' : 'text-red-500'}`}>
                            {trend > 0 ? '↑' : '↓'} {Math.abs(trend)}% from prev
                        </p>
                    )}
                </div>
                <div className={`p-2 rounded-lg ${colorMap[color]}`}>
                    <Icon size={20} />
                </div>
            </div>
        </motion.div>
    );
};

export default SummaryCard;
