import { useState, useEffect } from 'react';
import SummaryCard from './SummaryCard';
import GeneticProgressionChart from './GeneticProgressionChart';
import ScenarioTable from './ScenarioTable';
import { loadAllData } from '../lib/data-parser';
import { Activity, Beaker, Target, Clock, RefreshCw } from 'lucide-react';

const Dashboard = () => {
    const [data, setData] = useState({ results: null, scenarios: [], isLoaded: false });
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        const fetchData = async () => {
            try {
                const result = await loadAllData();
                setData(result);
                setLoading(false);
            } catch (err) {
                setError('Failed to load dashboard data. Ensure krkn-ai results are available.');
                setLoading(false);
            }
        };
        fetchData();
    }, []);

    if (loading) {
        return (
            <div className="flex items-center justify-center min-h-screen bg-background">
                <div className="flex flex-col items-center gap-4">
                    <RefreshCw className="animate-spin text-primary" size={48} />
                    <p className="text-muted-foreground font-medium">Crunching results...</p>
                </div>
            </div>
        );
    }

    if (error || !data.isLoaded) {
        return (
            <div className="flex items-center justify-center min-h-screen bg-background">
                <div className="max-w-md text-center p-8 border border-destructive/20 rounded-2xl bg-destructive/5">
                    <Beaker className="mx-auto text-destructive mb-4" size={48} />
                    <h2 className="text-xl font-bold mb-2">Results Not Found</h2>
                    <p className="text-muted-foreground mb-6">
                        We couldn't find any Krkn-AI results to visualize. Run an experiment first!
                    </p>
                    <button
                        onClick={() => window.location.reload()}
                        className="px-6 py-2 bg-primary text-primary-foreground rounded-lg font-medium hover:opacity-90 transition-opacity"
                    >
                        Retry
                    </button>
                </div>
            </div>
        );
    }

    const { results, scenarios } = data;

    return (
        <div className="min-h-screen bg-background pb-12">
            <header className="border-b border-border bg-card/50 backdrop-blur-xl sticky top-0 z-10">
                <div className="container mx-auto px-6 h-16 flex items-center justify-between">
                    <div className="flex items-center gap-3">
                        <div className="bg-primary p-1.5 rounded-lg">
                            <Beaker className="text-primary-foreground" size={20} />
                        </div>
                        <h1 className="font-bold text-xl tracking-tight">Krkn-AI <span className="text-muted-foreground font-normal ml-1">Dashboard</span></h1>
                    </div>
                    <div className="flex items-center gap-4 text-xs font-mono text-muted-foreground">
                        <span className="bg-secondary px-2 py-1 rounded">RUN_ID: {results.run_id.slice(0, 8)}...</span>
                    </div>
                </div>
            </header>

            <main className="container mx-auto px-6 mt-8">
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
                    <SummaryCard
                        title="Total Scenarios"
                        value={results.summary.total_scenarios_executed}
                        icon={Activity}
                        color="blue"
                    />
                    <SummaryCard
                        title="Generations"
                        value={results.summary.generations_completed}
                        icon={Beaker}
                        color="purple"
                    />
                    <SummaryCard
                        title="Best Fitness"
                        value={results.summary.best_fitness_score.toFixed(3)}
                        icon={Target}
                        color="green"
                        trend={12.5}
                    />
                    <SummaryCard
                        title="Avg Fitness"
                        value={results.summary.average_fitness_score.toFixed(3)}
                        icon={Clock}
                        color="yellow"
                    />
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-8">
                    <div className="lg:col-span-2">
                        <GeneticProgressionChart data={results.fitness_progression} />
                    </div>
                    <div className="p-6 rounded-xl border border-border bg-card">
                        <h3 className="text-lg font-semibold mb-4">Elite Scenarios</h3>
                        <div className="space-y-4">
                            {results.best_scenarios.map((s) => (
                                <div key={s.scenario_id} className="flex items-center justify-between p-3 rounded-lg bg-secondary/30 hover:bg-secondary/50 transition-colors group">
                                    <div>
                                        <p className="text-sm font-medium">{s.scenario_type}</p>
                                        <p className="text-[10px] text-muted-foreground font-mono mt-0.5">ID: {s.scenario_id} • GEN: {s.generation}</p>
                                    </div>
                                    <div className="text-right">
                                        <p className="text-sm font-bold text-primary">{s.fitness_score.toFixed(3)}</p>
                                        <div className="w-12 h-1 bg-secondary mt-1 rounded-full overflow-hidden">
                                            <div className="h-full bg-primary" style={{ width: `${s.fitness_score * 100}%` }} />
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>

                <ScenarioTable scenarios={scenarios} />
            </main>
        </div>
    );
};

export default Dashboard;
