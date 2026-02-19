import { useState, useEffect, useCallback } from 'react';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from './ui/card';
import { Badge } from './ui/badge';
import { Button } from './ui/button';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from 'recharts';
import { HistoryRecord } from '../types/kiln';
import { api } from '../services/api';
import { Download, Flame, Clock, Thermometer, Trash2 } from 'lucide-react';
import { toast } from 'sonner';

export function FiringHistory() {
  const [records, setRecords] = useState<HistoryRecord[]>([]);
  const [selectedRecord, setSelectedRecord] = useState<HistoryRecord | null>(null);
  const [traceData, setTraceData] = useState<{ time_s: number; temp_c: number }[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchHistory = useCallback(async () => {
    try {
      const data = await api.getHistory();
      setRecords(data);
    } catch {
      // Not connected or no history
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchHistory();
  }, [fetchHistory]);

  const handleSelectRecord = async (record: HistoryRecord) => {
    setSelectedRecord(record);
    setTraceData([]);
    try {
      const url = api.getHistoryTrace(record.id);
      const res = await fetch(url);
      if (res.ok) {
        const csv = await res.text();
        const lines = csv.trim().split('\n').slice(1); // skip header
        const parsed = lines
          .map((line) => {
            const [time_s, temp_c] = line.split(',').map(Number);
            return { time_s, temp_c };
          })
          .filter((d) => !isNaN(d.time_s) && !isNaN(d.temp_c));
        setTraceData(parsed);
      }
    } catch {
      // No trace available
    }
  };

  const handleDownloadTrace = (record: HistoryRecord) => {
    const url = api.getHistoryTrace(record.id);
    const a = document.createElement('a');
    a.href = url;
    a.download = `trace_${record.id}.csv`;
    a.click();
    toast.success('Downloading trace CSV');
  };

  const formatDuration = (s: number) => {
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    return `${h}h ${m}m`;
  };

  const formatDate = (timestamp: number) => {
    if (!timestamp) return 'Unknown date';
    return new Date(timestamp * 1000).toLocaleString();
  };

  const outcomeVariant = (outcome: string): 'default' | 'secondary' | 'destructive' | 'outline' => {
    if (outcome === 'complete') return 'default';
    if (outcome === 'error') return 'destructive';
    return 'outline';
  };

  if (loading) {
    return (
      <Card>
        <CardContent className="py-12 text-center">
          <p className="text-muted-foreground">Loading history...</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-2xl font-semibold mb-2">Firing History</h2>
        <p className="text-muted-foreground">
          Records of past firings. Click a record to view the temperature trace.
        </p>
      </div>

      {records.length === 0 ? (
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-muted-foreground">No firing history yet.</p>
            <p className="text-sm text-muted-foreground mt-2">
              Complete a firing to see records here.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {/* Record list */}
          <div className="space-y-3 lg:col-span-1">
            {records.map((record) => (
              <Card
                key={record.id}
                className={`cursor-pointer transition-all ${
                  selectedRecord?.id === record.id ? 'ring-2 ring-primary' : 'hover:shadow-md'
                }`}
                onClick={() => handleSelectRecord(record)}
              >
                <CardContent className="pt-4 pb-3 space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-sm truncate">{record.profileName}</span>
                    <Badge variant={outcomeVariant(record.outcome)} className="ml-2 shrink-0">
                      {record.outcome}
                    </Badge>
                  </div>
                  <p className="text-xs text-muted-foreground">{formatDate(record.startTime)}</p>
                  <div className="flex gap-3 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1">
                      <Thermometer className="h-3 w-3" />
                      {Math.round(record.peakTemp)}°C
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {formatDuration(record.durationS)}
                    </span>
                  </div>
                  <Button
                    variant="outline"
                    size="sm"
                    className="w-full mt-1 gap-1"
                    onClick={(e) => {
                      e.stopPropagation();
                      handleDownloadTrace(record);
                    }}
                  >
                    <Download className="h-3 w-3" />
                    CSV
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>

          {/* Trace chart */}
          <div className="lg:col-span-2">
            {selectedRecord ? (
              <Card>
                <CardHeader>
                  <div className="flex items-start justify-between">
                    <div>
                      <CardTitle className="flex items-center gap-2">
                        <Flame className="h-5 w-5" />
                        {selectedRecord.profileName}
                      </CardTitle>
                      <CardDescription>{formatDate(selectedRecord.startTime)}</CardDescription>
                    </div>
                    <Badge variant={outcomeVariant(selectedRecord.outcome)}>
                      {selectedRecord.outcome}
                    </Badge>
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-3 gap-4 mb-4">
                    <div className="text-center p-3 bg-muted/50 rounded-lg">
                      <p className="text-xs text-muted-foreground">Peak Temp</p>
                      <p className="text-xl font-bold">{Math.round(selectedRecord.peakTemp)}°C</p>
                    </div>
                    <div className="text-center p-3 bg-muted/50 rounded-lg">
                      <p className="text-xs text-muted-foreground">Duration</p>
                      <p className="text-xl font-bold">{formatDuration(selectedRecord.durationS)}</p>
                    </div>
                    <div className="text-center p-3 bg-muted/50 rounded-lg">
                      <p className="text-xs text-muted-foreground">Outcome</p>
                      <p className="text-xl font-bold capitalize">{selectedRecord.outcome}</p>
                    </div>
                  </div>

                  {traceData.length > 0 ? (
                    <ResponsiveContainer width="100%" height={300}>
                      <LineChart data={traceData}>
                        <CartesianGrid strokeDasharray="3 3" />
                        <XAxis
                          dataKey="time_s"
                          tickFormatter={(v) => `${Math.round(v / 60)}m`}
                          label={{ value: 'Time', position: 'insideBottom', offset: -5 }}
                        />
                        <YAxis
                          label={{ value: 'Temp (°C)', angle: -90, position: 'insideLeft' }}
                        />
                        <Tooltip
                          formatter={(v: number) => [`${v}°C`, 'Temperature']}
                          labelFormatter={(v) => `${Math.round(Number(v) / 60)} min`}
                        />
                        <Line
                          type="monotone"
                          dataKey="temp_c"
                          stroke="#ef4444"
                          strokeWidth={2}
                          dot={false}
                          name="Temperature"
                        />
                      </LineChart>
                    </ResponsiveContainer>
                  ) : (
                    <div className="h-[300px] flex items-center justify-center text-muted-foreground">
                      <p>No temperature trace available for this record.</p>
                    </div>
                  )}

                  <Button
                    variant="outline"
                    className="mt-4 gap-2"
                    onClick={() => handleDownloadTrace(selectedRecord)}
                  >
                    <Download className="h-4 w-4" />
                    Download CSV Trace
                  </Button>
                </CardContent>
              </Card>
            ) : (
              <Card>
                <CardContent className="py-20 text-center">
                  <Flame className="h-12 w-12 mx-auto text-muted-foreground mb-4" />
                  <p className="text-muted-foreground">Select a firing record to view its temperature trace.</p>
                </CardContent>
              </Card>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
