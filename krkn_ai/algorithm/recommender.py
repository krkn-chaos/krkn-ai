from krkn_ai.utils.prometheus import create_prometheus_client

class ScenarioRecommender:
    scenarios = ['pod-scenarios', 'container-scenarios', 'node-cpu-hog', 'node-memory-hog']
    
    def __init__(self, kubeconfig):
        self.kube = kubeconfig
        self.prom = None
    
    def _q(self, query):
        try:
            if not self.prom:
                self.prom = create_prometheus_client(self.kube)
            r = self.prom.process_query(query)
            return float(r[0]['value'][1]) if r else 0.0
        except:
            return 0.0
    
    def get_metrics(self, t='15m'):
        return {
            'cpu': self._q(f'max(rate(node_cpu_seconds_total{{mode!="idle"}}[{t}]))'),
            'mem': 1.0 - self._q('avg(node_memory_MemAvailable_bytes/node_memory_MemTotal_bytes)'),
            'restarts': self._q(f'sum(rate(kube_pod_container_status_restarts_total[{t}]))'),
            'oom': self._q(f'sum(rate(container_oom_events_total[{t}]))')
        }
    
    def recommend(self, timerange='15m', top=3):
        m = self.get_metrics(timerange)
        results = []
        if m['restarts'] > 0.05:
            results.append(('pod-scenarios', min(m['restarts'] * 10, 1.0), f"restarts: {m['restarts']:.3f}/s"))
        if m['oom'] > 0.01:
            results.append(('container-scenarios', min(m['oom'] * 50, 1.0), f"OOM: {m['oom']:.3f}/s"))
        if m['cpu'] > 0.7:
            results.append(('node-cpu-hog', m['cpu'], f"CPU: {m['cpu']:.0%}"))
        if m['mem'] > 0.7:
            results.append(('node-memory-hog', m['mem'], f"mem: {m['mem']:.0%}"))
        results.sort(key=lambda x: x[1], reverse=True)
        return [{'scenario': s, 'confidence': c, 'reason': r} for s, c, r in results[:top]]
