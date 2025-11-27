# Evaluator Metrics Repair - Quick Reference & Verification

## Files Modified

1. **backend/agents/agent1/evaluator_agent/evaluator_api.py** (lines 107-125)
   - Added `build_score_breakdown()` call to generate detailed metrics
   - Updated `agent_scores` structure to include proper breakdown

2. **frontend/src/components/EvaluatorView.jsx** (lines 459-530)
   - Changed from hard-coded `['agent1', 'agent2', 'agent3']` to `Object.keys(agentScores)`
   - Added guards for missing metrics with placeholder display
   - Made component dynamic and adaptive

## How to Verify the Fix

### Quick Check
```bash
# Terminal 1: Start the backend if not running
cd agents/agent1/evaluator_agent
python evaluator_api.py

# Terminal 2: Test the endpoint
curl -s http://localhost:8000/status | jq '.agent_scores["agent1"].breakdown'
```

Expected output should show:
```json
{
  "correctness": 0.92,
  "efficiency": 0.85,
  "quality": 0.88,
  "stability": 0.80,
  "autonomy": 0.75,
  "resource_efficiency": 0.90
}
```

### Frontend Verification Checklist

When you open the Evaluator tab:

- [ ] **"Performance by Agent" section shows**:
  - Only agents that have data (no empty cards for missing agents)
  - Each agent shows a percentage score (e.g., "85.5%")
  - A colored progress bar (green/yellow/red based on score)

- [ ] **Clicking an agent card expands to show**:
  - Score Breakdown section with 6 metrics:
    - Correctness
    - Efficiency
    - Quality
    - Stability
    - Autonomy
    - Resource Efficiency
  - Raw Metrics section showing:
    - Time: X.Xs
    - Errors: Y
    - API Calls: Z
    - Cost: $X.XX

- [ ] **If metrics are not available yet**:
  - Shows placeholder text: "Metrics not yet available. Processing..."
  - No errors in console

### Console Log Verification

Open browser DevTools (F12) → Console tab:

Should NOT see errors like:
- ❌ "Cannot read property 'breakdown' of undefined"
- ❌ "Cannot read property 'metrics' of undefined"

Should see normal fetch:
- ✓ `GET /evaluator/status 200 OK`

### Backend Data Flow

The fix ensures data flows correctly:

```
MongoDB logs (collector)
    ↓
metrics computed (collector.compute_basic_metrics)
    ↓
task_data includes metrics
    ↓
scorer.score_task(task_data) → returns scores + metrics
    ↓
builder.build_report() → report includes metrics
    ↓
evaluator_api.get_status() → builds agent_scores with breakdown
    ↓
frontend receives complete payload
    ↓
ScoreBreakdown renders all metrics
```

## Testing With Mock Data

If you want to test without waiting for actual evaluations:

1. Create a mock response in test_evaluator_payload.py
2. Or manually construct a JSON response matching the expected structure:

```json
{
  "agent_scores": {
    "agent1": {
      "score": 85.5,
      "breakdown": {
        "correctness": 0.92,
        "efficiency": 0.85,
        "quality": 0.88,
        "stability": 0.80,
        "autonomy": 0.75,
        "resource_efficiency": 0.90
      },
      "metrics": {
        "completion_time_s": 45.3,
        "error_count": 2,
        "total_api_calls": 15,
        "cost_usd": 0.08
      }
    }
  }
}
```

## Troubleshooting

### Issue: Metrics showing as 0

**Check**:
1. Are MongoDB logs being collected?
   ```bash
   db.logs.countDocuments()  # Should be > 0
   ```

2. Is data_collector computing metrics?
   ```python
   # In collector.collect_for_task()
   metrics = self.mongo.compute_basic_metrics(logs)
   # Should have: error_count, completion_time_s, total_api_calls, cost_usd
   ```

3. Is build_score_breakdown being called?
   - Search evaluator_api.py for "breakdown = build_score_breakdown"
   - Should be on line ~107

### Issue: Only some agents showing

**Check**:
1. Are all agents present in all_reports?
   ```python
   agents = set()
   for report in all_reports:
       agents.add(report.get("agent_id"))
   # Should have all agents
   ```

2. Frontend is now dynamic - it shows only agents that are in agent_scores
3. If you expect more agents, check if scheduler is evaluating them

### Issue: Metrics visible in JSON but not in UI

**Check**:
1. Open DevTools → Network tab → /evaluator/status
2. Verify response has agent_scores with breakdown
3. If yes, check if component is rendering breakdown:
   ```javascript
   console.log('breakdown:', data?.breakdown);
   console.log('metrics:', data?.metrics);
   ```

## Code Changes Summary

### Before (backend):
```python
agent_scores[agent_id] = {
    "breakdown": report.get("scores", {}),  # ❌ Only 2 fields
    "metrics": report.get("metrics", {}),   # ✓ But not used in breakdown
}
```

### After (backend):
```python
breakdown = build_score_breakdown(report_scores, report_metrics, is_completed)
agent_scores[agent_id] = {
    "breakdown": breakdown,  # ✓ Full breakdown with 6 metrics
    "metrics": report_metrics,  # ✓ Raw metrics included
}
```

### Before (frontend):
```javascript
{['agent1', 'agent2', 'agent3'].map(agentId => {  // ❌ Hard-coded
    const data = agentScores[agentId];  // ❌ Will show empty cards
})}
```

### After (frontend):
```javascript
{Object.keys(agentScores).length === 0 ? (
    <placeholder />
) : (
    Object.entries(agentScores).map(([agentId, scoreData]) => {  // ✓ Dynamic
        const data = feedbackEntry?.performance_details || scoreData;  // ✓ With guards
        if (Object.keys(breakdown).length > 0 || Object.keys(metrics).length > 0) {
            // ✓ Render only when data exists
        }
    })
)}
```

## Performance Impact

- ✓ Minimal: Only adds one function call per agent in /status endpoint
- ✓ build_score_breakdown() is O(1) - simple calculations
- ✓ No additional database queries
- ✓ Frontend rendering is more efficient (no empty cards)

## Next Steps

1. Test with real agent evaluations
2. Monitor for any missing metric fields
3. Verify metrics are non-zero and make sense
4. Check UI responsiveness with dynamic agents
5. Monitor console for any React warnings

## Support

If metrics are still not showing:
1. Check EVALUATOR_METRICS_REPAIR.md for detailed explanation
2. Run test_evaluator_payload.py to validate backend structure
3. Check browser console for component errors
4. Verify MongoDB has data with sample queries
