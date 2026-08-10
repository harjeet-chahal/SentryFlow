import React, { useState, useEffect } from 'react';
import { useAuth } from '../components/auth/AuthContext';
import { Line, Bar, Pie } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
  Filler
} from 'chart.js';
import { format } from 'date-fns';

// Register ChartJS components
ChartJS.register(
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  ArcElement,
  Title,
  Tooltip,
  Legend,
  Filler
);

const Dashboard = () => {
  const { authAxios } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [metrics, setMetrics] = useState({
    totalRequests: 0,
    avgResponseTime: 0,
    errorRate: 0,
    rateLimitedRequests: 0
  });
  const [timeRangeFilter, setTimeRangeFilter] = useState('24h'); // 1h, 24h, 7d, 30d
  const [requestsData, setRequestsData] = useState(null);
  const [responseTimeData, setResponseTimeData] = useState(null);
  const [statusCodeData, setStatusCodeData] = useState(null);
  
  // Fetch dashboard data
  useEffect(() => {
    const fetchDashboardData = async () => {
      try {
        setLoading(true);
        setError(null);
        
        // In a real app, these would be actual API calls
        // const metricsResponse = await authAxios.get(`/api/metrics?timeRange=${timeRangeFilter}`);
        // const requestsResponse = await authAxios.get(`/api/metrics/requests?timeRange=${timeRangeFilter}`);
        // const responseTimeResponse = await authAxios.get(`/api/metrics/response-time?timeRange=${timeRangeFilter}`);
        // const statusCodeResponse = await authAxios.get(`/api/metrics/status-codes?timeRange=${timeRangeFilter}`);
        
        // For demo purposes, we'll use mock data
        const mockData = generateMockData(timeRangeFilter);
        
        setMetrics(mockData.metrics);
        setRequestsData(mockData.requestsData);
        setResponseTimeData(mockData.responseTimeData);
        setStatusCodeData(mockData.statusCodeData);
      } catch (err) {
        console.error('Error fetching dashboard data:', err);
        setError('Failed to load dashboard data');
      } finally {
        setLoading(false);
      }
    };
    
    fetchDashboardData();
  }, [authAxios, timeRangeFilter]);
  
  // Generate mock data for demo
  const generateMockData = (timeRange) => {
    // Generate time labels based on selected range
    const labels = [];
    const requestsValues = [];
    const responseTimeValues = [];
    
    let dataPoints = 0;
    let timeFormat = '';
    
    switch (timeRange) {
      case '1h':
        dataPoints = 12; // 5-minute intervals
        timeFormat = 'HH:mm';
        break;
      case '24h':
        dataPoints = 24; // 1-hour intervals
        timeFormat = 'HH:mm';
        break;
      case '7d':
        dataPoints = 7; // 1-day intervals
        timeFormat = 'MMM dd';
        break;
      case '30d':
        dataPoints = 30; // 1-day intervals
        timeFormat = 'MMM dd';
        break;
      default:
        dataPoints = 24;
        timeFormat = 'HH:mm';
    }
    
    // Generate time labels and data points
    for (let i = 0; i < dataPoints; i++) {
      const date = new Date();
      
      if (timeRange === '1h') {
        date.setMinutes(date.getMinutes() - (dataPoints - i) * 5);
      } else if (timeRange === '24h') {
        date.setHours(date.getHours() - (dataPoints - i));
      } else {
        date.setDate(date.getDate() - (dataPoints - i));
      }
      
      labels.push(format(date, timeFormat));
      
      // Generate random data
      const baseRequests = 100;
      const randomFactor = Math.random() * 0.5 + 0.75; // 0.75 to 1.25
      const requests = Math.floor(baseRequests * randomFactor);
      requestsValues.push(requests);
      
      const baseResponseTime = 120;
      const responseTimeFactor = Math.random() * 0.6 + 0.7; // 0.7 to 1.3
      const responseTime = Math.floor(baseResponseTime * responseTimeFactor);
      responseTimeValues.push(responseTime);
    }
    
    // Calculate summary metrics
    const totalRequests = requestsValues.reduce((sum, val) => sum + val, 0);
    const avgResponseTime = Math.floor(
      responseTimeValues.reduce((sum, val) => sum + val, 0) / responseTimeValues.length
    );
    const errorRate = Math.floor(Math.random() * 5); // 0-5%
    const rateLimitedRequests = Math.floor(totalRequests * (Math.random() * 0.03)); // 0-3%
    
    // Status code distribution
    const statusCodes = {
      '2xx': 100 - errorRate - Math.floor(Math.random() * 2),
      '3xx': Math.floor(Math.random() * 2),
      '4xx': errorRate - Math.floor(errorRate / 2),
      '5xx': Math.floor(errorRate / 2)
    };
    
    return {
      metrics: {
        totalRequests,
        avgResponseTime,
        errorRate,
        rateLimitedRequests
      },
      requestsData: {
        labels,
        datasets: [
          {
            label: 'Requests per Second',
            data: requestsValues,
            borderColor: 'rgb(59, 130, 246)',
            backgroundColor: 'rgba(59, 130, 246, 0.1)',
            fill: true,
            tension: 0.4
          }
        ]
      },
      responseTimeData: {
        labels,
        datasets: [
          {
            label: 'Avg Response Time (ms)',
            data: responseTimeValues,
            borderColor: 'rgb(16, 185, 129)',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            fill: true,
            tension: 0.4
          }
        ]
      },
      statusCodeData: {
        labels: Object.keys(statusCodes),
        datasets: [
          {
            label: 'Status Code Distribution',
            data: Object.values(statusCodes),
            backgroundColor: [
              'rgba(16, 185, 129, 0.7)',  // 2xx - Green
              'rgba(59, 130, 246, 0.7)',  // 3xx - Blue
              'rgba(245, 158, 11, 0.7)',  // 4xx - Yellow
              'rgba(239, 68, 68, 0.7)'    // 5xx - Red
            ],
            borderWidth: 1
          }
        ]
      }
    };
  };
  
  // Chart options
  const lineChartOptions = {
    responsive: true,
    plugins: {
      legend: {
        position: 'top',
      },
      tooltip: {
        mode: 'index',
        intersect: false,
      }
    },
    scales: {
      y: {
        beginAtZero: true
      }
    },
    interaction: {
      mode: 'nearest',
      axis: 'x',
      intersect: false
    }
  };
  
  const pieChartOptions = {
    responsive: true,
    plugins: {
      legend: {
        position: 'top',
      },
      tooltip: {
        callbacks: {
          label: function(context) {
            const label = context.label || '';
            const value = context.raw || 0;
            return `${label}: ${value}%`;
          }
        }
      }
    }
  };
  
  // Handle time range filter change
  const handleTimeRangeChange = (range) => {
    setTimeRangeFilter(range);
  };
  
  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
      </div>
    );
  }
  
  if (error) {
    return (
      <div className="bg-red-50 p-4 rounded-md">
        <div className="flex">
          <div className="ml-3">
            <h3 className="text-sm font-medium text-red-800">{error}</h3>
          </div>
        </div>
      </div>
    );
  }
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-gray-900">Dashboard Overview</h1>
        
        <div className="flex space-x-2">
          <button
            onClick={() => handleTimeRangeChange('1h')}
            className={`px-3 py-1 text-sm rounded-md ${timeRangeFilter === '1h' ? 'bg-blue-600 text-white' : 'bg-gray-200 text-gray-700 hover:bg-gray-300'}`}
          >
            1h
          </button>
          <button
            onClick={() => handleTimeRangeChange('24h')}
            className={`px-3 py-1 text-sm rounded-md ${timeRangeFilter === '24h' ? 'bg-blue-600 text-white' : 'bg-gray-200 text-gray-700 hover:bg-gray-300'}`}
          >
            24h
          </button>
          <button
            onClick={() => handleTimeRangeChange('7d')}
            className={`px-3 py-1 text-sm rounded-md ${timeRangeFilter === '7d' ? 'bg-blue-600 text-white' : 'bg-gray-200 text-gray-700 hover:bg-gray-300'}`}
          >
            7d
          </button>
          <button
            onClick={() => handleTimeRangeChange('30d')}
            className={`px-3 py-1 text-sm rounded-md ${timeRangeFilter === '30d' ? 'bg-blue-600 text-white' : 'bg-gray-200 text-gray-700 hover:bg-gray-300'}`}
          >
            30d
          </button>
        </div>
      </div>
      
      {/* Metrics cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <div className="dashboard-card">
          <h3 className="text-lg font-medium text-gray-900">Total Requests</h3>
          <p className="mt-2 text-3xl font-semibold text-blue-600">{metrics.totalRequests.toLocaleString()}</p>
          <p className="mt-1 text-sm text-gray-500">In selected time period</p>
        </div>
        
        <div className="dashboard-card">
          <h3 className="text-lg font-medium text-gray-900">Avg Response Time</h3>
          <p className="mt-2 text-3xl font-semibold text-green-600">{metrics.avgResponseTime} ms</p>
          <p className="mt-1 text-sm text-gray-500">Across all endpoints</p>
        </div>
        
        <div className="dashboard-card">
          <h3 className="text-lg font-medium text-gray-900">Error Rate</h3>
          <p className="mt-2 text-3xl font-semibold text-yellow-600">{metrics.errorRate}%</p>
          <p className="mt-1 text-sm text-gray-500">4xx and 5xx responses</p>
        </div>
        
        <div className="dashboard-card">
          <h3 className="text-lg font-medium text-gray-900">Rate Limited</h3>
          <p className="mt-2 text-3xl font-semibold text-red-600">{metrics.rateLimitedRequests.toLocaleString()}</p>
          <p className="mt-1 text-sm text-gray-500">429 responses</p>
        </div>
      </div>
      
      {/* Charts */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="chart-container">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Requests Over Time</h3>
          {requestsData && <Line data={requestsData} options={lineChartOptions} />}
        </div>
        
        <div className="chart-container">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Response Time</h3>
          {responseTimeData && <Line data={responseTimeData} options={lineChartOptions} />}
        </div>
      </div>
      
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="chart-container">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Status Code Distribution</h3>
          <div className="h-64">
            {statusCodeData && <Pie data={statusCodeData} options={pieChartOptions} />}
          </div>
        </div>
        
        <div className="chart-container">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Top Endpoints</h3>
          <div className="h-64">
            <Bar
              data={{
                labels: ["/api/v1/data", "/api/v1/users", "/api/v1/auth", "/api/v1/products", "/api/v1/orders"],
                datasets: [
                  {
                    label: 'Requests',
                    data: [65, 59, 80, 81, 56],
                    backgroundColor: 'rgba(59, 130, 246, 0.7)',
                  }
                ],
              }}
              options={{
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
              }}
            />
          </div>
        </div>
      </div>
    </div>
  );
};

export default Dashboard;