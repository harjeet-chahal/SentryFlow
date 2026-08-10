import React, { useState, useEffect } from 'react';
import { useAuth } from '../components/auth/AuthContext';
import { Line, Bar, Doughnut } from 'react-chartjs-2';
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

const UserView = () => {
  const { authAxios } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [users, setUsers] = useState([]);
  const [selectedUser, setSelectedUser] = useState(null);
  const [userMetrics, setUserMetrics] = useState(null);
  const [timeRangeFilter, setTimeRangeFilter] = useState('24h'); // 1h, 24h, 7d, 30d
  
  // Fetch users
  useEffect(() => {
    const fetchUsers = async () => {
      try {
        setLoading(true);
        setError(null);
        
        // In a real app, this would be an actual API call
        // const response = await authAxios.get('/api/users');
        // setUsers(response.data);
        
        // For demo purposes, we'll use mock data
        const mockUsers = [
          { id: 'user_123', name: 'John Doe', email: 'john@example.com' },
          { id: 'user_456', name: 'Jane Smith', email: 'jane@example.com' },
          { id: 'user_789', name: 'Bob Johnson', email: 'bob@example.com' },
          { id: 'user_abc', name: 'Alice Williams', email: 'alice@example.com' },
          { id: 'user_def', name: 'Charlie Brown', email: 'charlie@example.com' }
        ];
        
        setUsers(mockUsers);
        
        // Select the first user by default
        if (mockUsers.length > 0 && !selectedUser) {
          setSelectedUser(mockUsers[0].id);
        }
      } catch (err) {
        console.error('Error fetching users:', err);
        setError('Failed to load users');
      } finally {
        setLoading(false);
      }
    };
    
    fetchUsers();
  }, [authAxios, selectedUser]);
  
  // Fetch user metrics when user or time range changes
  useEffect(() => {
    const fetchUserMetrics = async () => {
      if (!selectedUser) return;
      
      try {
        setLoading(true);
        setError(null);
        
        // In a real app, this would be an actual API call
        // const response = await authAxios.get(`/api/metrics/users/${selectedUser}?timeRange=${timeRangeFilter}`);
        // setUserMetrics(response.data);
        
        // For demo purposes, we'll use mock data
        const mockMetrics = generateMockUserMetrics(selectedUser, timeRangeFilter);
        setUserMetrics(mockMetrics);
      } catch (err) {
        console.error('Error fetching user metrics:', err);
        setError('Failed to load user metrics');
      } finally {
        setLoading(false);
      }
    };
    
    fetchUserMetrics();
  }, [authAxios, selectedUser, timeRangeFilter]);
  
  // Generate mock user metrics for demo
  const generateMockUserMetrics = (userId, timeRange) => {
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
      
      // Generate random data with some variance based on user ID
      // This creates different patterns for different users
      const userVariance = userId.charCodeAt(userId.length - 1) % 5 + 0.8; // 0.8 to 1.3
      
      const baseRequests = 50;
      const randomFactor = Math.random() * 0.5 + 0.75; // 0.75 to 1.25
      const requests = Math.floor(baseRequests * randomFactor * userVariance);
      requestsValues.push(requests);
      
      const baseResponseTime = 100;
      const responseTimeFactor = Math.random() * 0.6 + 0.7; // 0.7 to 1.3
      const responseTime = Math.floor(baseResponseTime * responseTimeFactor * userVariance);
      responseTimeValues.push(responseTime);
    }
    
    // Generate endpoint distribution
    const endpoints = [
      '/api/v1/data',
      '/api/v1/users',
      '/api/v1/auth',
      '/api/v1/products',
      '/api/v1/orders'
    ];
    
    const endpointDistribution = {};
    let totalRequests = 0;
    
    endpoints.forEach(endpoint => {
      // Generate a random number of requests for each endpoint
      // with some variance based on user ID to create different patterns
      const userVariance = userId.charCodeAt(userId.length - 1) % 5 + 0.8; // 0.8 to 1.3
      const requests = Math.floor(Math.random() * 100 * userVariance);
      endpointDistribution[endpoint] = requests;
      totalRequests += requests;
    });
    
    // Generate status code distribution
    const statusCodes = {
      '2xx': 90 + Math.floor(Math.random() * 10), // 90-99%
      '3xx': Math.floor(Math.random() * 3),       // 0-2%
      '4xx': Math.floor(Math.random() * 5),       // 0-4%
      '5xx': Math.floor(Math.random() * 2)        // 0-1%
    };
    
    // Ensure percentages add up to 100%
    const sum = Object.values(statusCodes).reduce((a, b) => a + b, 0);
    Object.keys(statusCodes).forEach(key => {
      statusCodes[key] = Math.round((statusCodes[key] / sum) * 100);
    });
    
    // Calculate summary metrics
    const avgResponseTime = Math.floor(
      responseTimeValues.reduce((sum, val) => sum + val, 0) / responseTimeValues.length
    );
    
    const rateLimitedRequests = Math.floor(totalRequests * (Math.random() * 0.05)); // 0-5%
    
    return {
      summary: {
        totalRequests,
        avgResponseTime,
        rateLimitedRequests,
        errorRate: statusCodes['4xx'] + statusCodes['5xx']
      },
      requestsData: {
        labels,
        datasets: [
          {
            label: 'Requests',
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
            label: 'Response Time (ms)',
            data: responseTimeValues,
            borderColor: 'rgb(16, 185, 129)',
            backgroundColor: 'rgba(16, 185, 129, 0.1)',
            fill: true,
            tension: 0.4
          }
        ]
      },
      endpointDistribution: {
        labels: Object.keys(endpointDistribution),
        datasets: [
          {
            label: 'Requests by Endpoint',
            data: Object.values(endpointDistribution),
            backgroundColor: [
              'rgba(59, 130, 246, 0.7)',  // Blue
              'rgba(16, 185, 129, 0.7)',  // Green
              'rgba(245, 158, 11, 0.7)',  // Yellow
              'rgba(239, 68, 68, 0.7)',   // Red
              'rgba(139, 92, 246, 0.7)'   // Purple
            ],
            borderWidth: 1
          }
        ]
      },
      statusCodeDistribution: {
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
  
  const doughnutChartOptions = {
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
  
  // Handle user change
  const handleUserChange = (e) => {
    setSelectedUser(e.target.value);
  };
  
  // Handle time range filter change
  const handleTimeRangeChange = (range) => {
    setTimeRangeFilter(range);
  };
  
  if (loading && !userMetrics) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
      </div>
    );
  }
  
  return (
    <div className="space-y-6">
      <div className="flex flex-col md:flex-row md:items-center md:justify-between space-y-4 md:space-y-0">
        <h1 className="text-2xl font-semibold text-gray-900">User View</h1>
        
        <div className="flex flex-col md:flex-row space-y-4 md:space-y-0 md:space-x-4">
          {/* User selector */}
          <div className="w-full md:w-64">
            <select
              className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              value={selectedUser || ''}
              onChange={handleUserChange}
            >
              <option value="">Select a user</option>
              {users.map(user => (
                <option key={user.id} value={user.id}>
                  {user.name} ({user.email})
                </option>
              ))}
            </select>
          </div>
          
          {/* Time range filter */}
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
      </div>
      
      {error ? (
        <div className="bg-red-50 p-4 rounded-md">
          <div className="flex">
            <div className="ml-3">
              <h3 className="text-sm font-medium text-red-800">{error}</h3>
            </div>
          </div>
        </div>
      ) : userMetrics ? (
        <>
          {/* Metrics cards */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
            <div className="dashboard-card">
              <h3 className="text-lg font-medium text-gray-900">Total Requests</h3>
              <p className="mt-2 text-3xl font-semibold text-blue-600">{userMetrics.summary.totalRequests.toLocaleString()}</p>
              <p className="mt-1 text-sm text-gray-500">In selected time period</p>
            </div>
            
            <div className="dashboard-card">
              <h3 className="text-lg font-medium text-gray-900">Avg Response Time</h3>
              <p className="mt-2 text-3xl font-semibold text-green-600">{userMetrics.summary.avgResponseTime} ms</p>
              <p className="mt-1 text-sm text-gray-500">Across all endpoints</p>
            </div>
            
            <div className="dashboard-card">
              <h3 className="text-lg font-medium text-gray-900">Error Rate</h3>
              <p className="mt-2 text-3xl font-semibold text-yellow-600">{userMetrics.summary.errorRate}%</p>
              <p className="mt-1 text-sm text-gray-500">4xx and 5xx responses</p>
            </div>
            
            <div className="dashboard-card">
              <h3 className="text-lg font-medium text-gray-900">Rate Limited</h3>
              <p className="mt-2 text-3xl font-semibold text-red-600">{userMetrics.summary.rateLimitedRequests.toLocaleString()}</p>
              <p className="mt-1 text-sm text-gray-500">429 responses</p>
            </div>
          </div>
          
          {/* Charts */}
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="chart-container">
              <h3 className="text-lg font-medium text-gray-900 mb-4">Requests Over Time</h3>
              {userMetrics.requestsData && <Line data={userMetrics.requestsData} options={lineChartOptions} />}
            </div>
            
            <div className="chart-container">
              <h3 className="text-lg font-medium text-gray-900 mb-4">Response Time</h3>
              {userMetrics.responseTimeData && <Line data={userMetrics.responseTimeData} options={lineChartOptions} />}
            </div>
          </div>
          
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
            <div className="chart-container">
              <h3 className="text-lg font-medium text-gray-900 mb-4">Endpoint Distribution</h3>
              <div className="h-64">
                {userMetrics.endpointDistribution && (
                  <Bar
                    data={userMetrics.endpointDistribution}
                    options={{
                      indexAxis: 'y',
                      responsive: true,
                      maintainAspectRatio: false,
                      plugins: {
                        legend: {
                          display: false
                        }
                      }
                    }}
                  />
                )}
              </div>
            </div>
            
            <div className="chart-container">
              <h3 className="text-lg font-medium text-gray-900 mb-4">Status Code Distribution</h3>
              <div className="h-64 flex items-center justify-center">
                {userMetrics.statusCodeDistribution && (
                  <Doughnut
                    data={userMetrics.statusCodeDistribution}
                    options={doughnutChartOptions}
                  />
                )}
              </div>
            </div>
          </div>
        </>
      ) : (
        <div className="bg-yellow-50 p-4 rounded-md">
          <div className="flex">
            <div className="ml-3">
              <h3 className="text-sm font-medium text-yellow-800">Please select a user to view their metrics</h3>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

export default UserView;