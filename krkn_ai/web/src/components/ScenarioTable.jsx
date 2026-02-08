import React, { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';
import { Search, AlertCircle, CheckCircle, Activity } from 'lucide-react';

const ScenarioTable = ({ scenarios }) => {
    const [searchTerm, setSearchTerm] = useState('');

    const filtered = scenarios.filter(s =>
        s.scenario?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        s.parameters?.toLowerCase().includes(searchTerm.toLowerCase())
    );

    return (
        <div className="mt-8">
            <div className="flex justify-between items-center mb-4">
                <h3 className="text-lg font-semibold">Scenario Execution History</h3>
                <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" size={16} />
                    <input
                        type="text"
                        placeholder="Search scenarios..."
                        className="pl-10 pr-4 py-2 bg-secondary border border-border rounded-lg text-sm focus:ring-1 focus:ring-primary outline-none transition-all w-64"
                        value={searchTerm}
                        onChange={(e) => setSearchTerm(e.target.value)}
                    />
                </div>
            </div>

            <div className="overflow-hidden rounded-xl border border-border bg-card">
                <table className="w-full text-left border-collapse">
                    <thead>
                        <tr className="bg-secondary/50 border-bottom border-border">
                            <th className="px-6 py-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Gen</th>
                            <th className="px-6 py-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Scenario</th>
                            <th className="px-6 py-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Fitness</th>
                            <th className="px-6 py-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Signals</th>
                            <th className="px-6 py-4 text-xs font-semibold text-muted-foreground uppercase tracking-wider">Status</th>
                        </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                        <AnimatePresence>
                            {filtered.map((s, i) => (
                                <motion.tr
                                    key={`${s.generation_id}-${s.scenario_id}`}
                                    initial={{ opacity: 0 }}
                                    animate={{ opacity: 1 }}
                                    exit={{ opacity: 0 }}
                                    transition={{ delay: i * 0.05 }}
                                    className="hover:bg-secondary/30 transition-colors"
                                >
                                    <td className="px-6 py-4 text-sm font-mono text-muted-foreground">{s.generation_id}</td>
                                    <td className="px-6 py-4">
                                        <div className="text-sm font-medium">{s.scenario}</div>
                                        <div className="text-xs text-muted-foreground mt-1 font-mono">{s.parameters}</div>
                                    </td>
                                    <td className="px-6 py-4">
                                        <div className="flex items-center gap-2">
                                            <div className="w-16 h-1.5 bg-secondary rounded-full overflow-hidden">
                                                <div
                                                    className={`h-full ${s.fitness_score > 0.7 ? 'bg-red-500' : s.fitness_score > 0.4 ? 'bg-yellow-500' : 'bg-green-500'}`}
                                                    style={{ width: `${s.fitness_score * 100}%` }}
                                                />
                                            </div>
                                            <span className="text-sm font-medium">{(s.fitness_score || 0).toFixed(3)}</span>
                                        </div>
                                    </td>
                                    <td className="px-6 py-4">
                                        <div className="flex gap-3">
                                            {s.krkn_failure_score > 0 && (
                                                <div title="Krkn Engine Failure" className="text-red-500 flex items-center gap-1">
                                                    <Activity size={14} />
                                                    <span className="text-xs">{(s.krkn_failure_score || 0).toFixed(1)}</span>
                                                </div>
                                            )}
                                            {s.health_check_failure_score > 0 && (
                                                <div title="Health Check Failure" className="text-orange-500 flex items-center gap-1">
                                                    <AlertCircle size={14} />
                                                    <span className="text-xs">{(s.health_check_failure_score || 0).toFixed(1)}</span>
                                                </div>
                                            )}
                                        </div>
                                    </td>
                                    <td className="px-6 py-4">
                                        {s.fitness_score > 0.8 ? (
                                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-red-500/10 text-red-500 border border-red-500/20">
                                                Critical Impact
                                            </span>
                                        ) : (
                                            <span className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-medium bg-green-500/10 text-green-500 border border-green-500/20">
                                                Stable
                                            </span>
                                        )}
                                    </td>
                                </motion.tr>
                            ))}
                        </AnimatePresence>
                    </tbody>
                </table>
            </div>
        </div>
    );
};

export default ScenarioTable;
