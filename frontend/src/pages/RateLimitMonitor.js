import React, { useState, useEffect } from 'react';
import { useAuth } from '../components/auth/AuthContext';
import { Line, Bar } from 'react-chartjs-2';
import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
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
  Title,
  Tooltip,
  Legend,
  Filler
);

const RateLimitMonitor = () => {
  const { authAxios } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [timeRangeFilter, setTimeRangeFilter] = useState('24h'); // 1h, 24h, 7d, 30d
  const [rateLimitData, setRateLimitData] = useState(null);
  const [endpointRateLimitData, setEndpointRateLimitData] = useState(null);
  const [rateLimitConfig, setRateLimitConfig] = useState([]);
  
  // Fetch rate limit data
  useEffect(() => {
    const fetchRateLimitData = async () => {
      try {
        setLoading(true);
        setError(null);
        
        // In a real app, these would be actual API calls
        // const rateLimitResponse = await authAxios.get(`/api/metrics/rate-limits?timeRange=${timeRangeFilter}`);
        // const endpointRateLimitResponse = await authAxios.get(`/api/metrics/rate-limits/endpoints?timeRange=${timeRangeFilter}`);
        // const rateLimitConfigResponse = await authAxios.get('/api/rate-limits/config');
        
        // For demo purposes, we'll use mock data
        const mockData = generateMockData(timeRangeFilter);
        
        setRateLimitData(mockData.rateLimitData);
        setEndpointRateLimitData(mockData.endpointRateLimitData);
        setRateLimitConfig(mockData.rateLimitConfig);
      } catch (err) {
        console.error('Error fetching rate limit data:', err);
        setError('Failed to load rate limit data');
      } finally {
        setLoading(false);
      }
    };
    
    fetchRateLimitData();
  }, [authAxios, timeRangeFilter]);
  
  // Generate mock data for demo
  const generateMockData = (timeRange) => {
    // Generate time labels based on selected range
    const labels = [];
    const successValues = [];
    const limitedValues = [];
    
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
      const successRequests = Math.floor(baseRequests * randomFactor);
      successValues.push(successRequests);
      
      // Generate rate limited requests (typically 0-10% of successful requests)
      const limitedRequests = Math.floor(successRequests * (Math.random() * 0.1));
      limitedValues.push(limitedRequests);
    }
    
    // Generate endpoint-specific rate limit data
    const endpoints = [
      '/api/v1/data',
      '/api/v1/users',
      '/api/v1/auth',
      '/api/v1/products',
      '/api/v1/orders'
    ];
    
    const endpointLimitedValues = endpoints.map(() => {
      return Math.floor(Math.random() * 50); // 0-50 rate limited requests per endpoint
    });
    
    // Generate rate limit configurations
    const rateLimitConfig = [
      {
        id: '1',
        endpoint: '/api/v1/data',
        method: 'GET',
        limit: 100,
        window: '1 minute',
        algorithm: 'sliding_window'
      },
      {
        id: '2',
        endpoint: '/api/v1/users',
        method: 'GET',
        limit: 50,
        window: '1 minute',
        algorithm: 'sliding_window'
      },
      {
        id: '3',
        endpoint: '/api/v1/auth',
        method: 'POST',
        limit: 10,
        window: '1 minute',
        algorithm: 'token_bucket'
      },
      {
        id: '4',
        endpoint: '/api/v1/products',
        method: 'GET',
        limit: 200,
        window: '1 minute',
        algorithm: 'sliding_window'
      },
      {
        id: '5',
        endpoint: '/api/v1/orders',
        method: 'POST',
        limit: 20,
        window: '1 minute',
        algorithm: 'token_bucket'
      }
    ];
    
    return {
      rateLimitData: {
        labels,
        datasets: [
          {
            label: 'Successful Requests',
            data: successValues,
            borderColor: 'rgb(16, 185, 129)',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            fill: true,
            tension: 0.4,
            yAxisID: 'y'
          },
          {
            label: 'Rate Limited Requests',
            data: limitedValues,
            borderColor: 'rgb(239, 68, 68)',
            backgroundColor: 'rgba(239, 68, 68, 0.1)',
            fill: true,
            tension: 0.4,
            yAxisID: 'y1'
          }
        ]
      },
      endpointRateLimitData: {
        labels: endpoints,
        datasets: [
          {
            label: 'Rate Limited Requests by Endpoint',
            data: endpointLimitedValues,
            backgroundColor: 'rgba(239, 68, 68, 0.7)',
            borderColor: 'rgb(239, 68, 68)',
            borderWidth: 1
          }
        ]
      },
      rateLimitConfig
    };
  };
  
  // Chart options
  const lineChartOptions = {
    responsive: true,
    interaction: {
      mode: 'index',
      intersect: false,
    },
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
        type: 'linear',
        display: true,
        position: 'left',
        title: {
          display: true,
          text: 'Successful Requests'
        },
        beginAtZero: true
      },
      y1: {
        type: 'linear',
        display: true,
        position: 'right',
        title: {
          display: true,
          text: 'Rate Limited Requests'
        },
        beginAtZero: true,
        grid: {
          drawOnChartArea: false,
        },
      },
    },
  };
  
  const barChartOptions = {
    responsive: true,
    plugins: {
      legend: {
        position: 'top',
      },
      tooltip: {
        callbacks: {
          label: function(context) {
            const label = context.dataset.label || '';
            const value = context.raw || 0;
            return `${label}: ${value}`;
          }
        }
      }
    },
    scales: {
      y: {
        beginAtZero: true,
        title: {
          display: true,
          text: 'Count'
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
        <h1 className="text-2xl font-semibold text-gray-900">Rate Limit Monitor</h1>
        
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
      
      {/* Rate limit charts */}
      <div className="grid grid-cols-1 gap-6">
        <div className="chart-container">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Rate Limited vs Successful Requests</h3>
          {rateLimitData && <Line data={rateLimitData} options={lineChartOptions} />}
        </div>
        
        <div className="chart-container">
          <h3 className="text-lg font-medium text-gray-900 mb-4">Rate Limited Requests by Endpoint</h3>
          {endpointRateLimitData && <Bar data={endpointRateLimitData} options={barChartOptions} />}
        </div>
      </div>
      
      {/* Rate limit configurations */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        <div className="px-4 py-5 sm:px-6">
          <h2 className="text-lg font-medium text-gray-900">Rate Limit Configurations</h2>
          <p className="mt-1 text-sm text-gray-500">Current rate limit settings for API endpoints</p>
        </div>
        
        <div className="border-t border-gray-200">
          <table className="min-w-full divide-y divide-gray-200">
            <thead className="bg-gray-50">
              <tr>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Endpoint
                </th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Method
                </th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Limit
                </th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Window
                </th>
                <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                  Algorithm
                </th>
              </tr>
            </thead>
            <tbody className="bg-white divide-y divide-gray-200">
              {rateLimitConfig.map((config) => (
                <tr key={config.id}>
                  <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                    {config.endpoint}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                      config.method === 'GET' ? 'bg-blue-100 text-blue-800' : 
                      config.method === 'POST' ? 'bg-green-100 text-green-800' : 
                      config.method === 'PUT' ? 'bg-yellow-100 text-yellow-800' : 
                      'bg-purple-100 text-purple-800'
                    }`}>
                      {config.method}
                    </span>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {config.limit} requests
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    {config.window}
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                    <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${
                      config.algorithm === 'sliding_window' ? 'bg-indigo-100 text-indigo-800' : 'bg-pink-100 text-pink-800'
                    }`}>
                      {config.algorithm === 'sliding_window' ? 'Sliding Window' : 'Token Bucket'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
};

export default RateLimitMonitor;