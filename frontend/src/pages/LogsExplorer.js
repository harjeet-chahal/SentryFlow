import React, { useState, useEffect } from 'react';
import { useAuth } from '../components/auth/AuthContext';
import { format } from 'date-fns';

const LogsExplorer = () => {
  const { authAxios } = useAuth();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [logs, setLogs] = useState([]);
  const [filteredLogs, setFilteredLogs] = useState([]);
  const [timeRangeFilter, setTimeRangeFilter] = useState('1h'); // 1h, 24h, 7d, 30d
  const [statusFilter, setStatusFilter] = useState('all'); // all, 2xx, 3xx, 4xx, 5xx
  const [endpointFilter, setEndpointFilter] = useState('');
  const [userIdFilter, setUserIdFilter] = useState('');
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const logsPerPage = 10;
  
  // Fetch logs
  useEffect(() => {
    const fetchLogs = async () => {
      try {
        setLoading(true);
        setError(null);
        
        // In a real app, this would be an actual API call
        // const response = await authAxios.get(`/api/logs?timeRange=${timeRangeFilter}`);
        // setLogs(response.data);
        
        // For demo purposes, we'll use mock data
        const mockLogs = generateMockLogs(timeRangeFilter, 100);
        setLogs(mockLogs);
      } catch (err) {
        console.error('Error fetching logs:', err);
        setError('Failed to load logs');
      } finally {
        setLoading(false);
      }
    };
    
    fetchLogs();
  }, [authAxios, timeRangeFilter]);
  
  // Apply filters
  useEffect(() => {
    let filtered = [...logs];
    
    // Apply status filter
    if (statusFilter !== 'all') {
      const statusRange = statusFilter.replace('xx', '');
      filtered = filtered.filter(log => {
        const statusFirstDigit = Math.floor(log.status_code / 100);
        return statusFirstDigit === parseInt(statusRange);
      });
    }
    
    // Apply endpoint filter
    if (endpointFilter) {
      filtered = filtered.filter(log => 
        log.endpoint.toLowerCase().includes(endpointFilter.toLowerCase())
      );
    }
    
    // Apply user ID filter
    if (userIdFilter) {
      filtered = filtered.filter(log => 
        log.user_id.toLowerCase().includes(userIdFilter.toLowerCase())
      );
    }
    
    setFilteredLogs(filtered);
    setTotalPages(Math.ceil(filtered.length / logsPerPage));
    setPage(1); // Reset to first page when filters change
  }, [logs, statusFilter, endpointFilter, userIdFilter]);
  
  // Generate mock logs for demo
  const generateMockLogs = (timeRange, count) => {
    const logs = [];
    const endpoints = [
      '/api/v1/data',
      '/api/v1/users',
      '/api/v1/auth',
      '/api/v1/products',
      '/api/v1/orders'
    ];
    const userIds = ['user_123', 'user_456', 'user_789', 'user_abc', 'user_def'];
    
    let timeRangeMs;
    switch (timeRange) {
      case '1h':
        timeRangeMs = 60 * 60 * 1000;
        break;
      case '24h':
        timeRangeMs = 24 * 60 * 60 * 1000;
        break;
      case '7d':
        timeRangeMs = 7 * 24 * 60 * 60 * 1000;
        break;
      case '30d':
        timeRangeMs = 30 * 24 * 60 * 60 * 1000;
        break;
      default:
        timeRangeMs = 60 * 60 * 1000;
    }
    
    for (let i = 0; i < count; i++) {
      // Generate random timestamp within the time range
      const timestamp = new Date(Date.now() - Math.random() * timeRangeMs);
      
      // Generate random status code with distribution
      let statusCode;
      const rand = Math.random();
      if (rand < 0.85) {
        statusCode = 200; // 85% are 200 OK
      } else if (rand < 0.9) {
        statusCode = 301; // 5% are 301 Moved Permanently
      } else if (rand < 0.97) {
        statusCode = 400 + Math.floor(Math.random() * 29); // 7% are 4xx errors
      } else {
        statusCode = 500 + Math.floor(Math.random() * 9); // 3% are 5xx errors
      }
      
      logs.push({
        id: `log-${i}`,
        timestamp,
        user_id: userIds[Math.floor(Math.random() * userIds.length)],
        endpoint: endpoints[Math.floor(Math.random() * endpoints.length)],
        status_code: statusCode,
        response_time: Math.floor(Math.random() * 500) + 50 // 50-550ms
      });
    }
    
    // Sort by timestamp (newest first)
    return logs.sort((a, b) => b.timestamp - a.timestamp);
  };
  
  // Format timestamp
  const formatTimestamp = (timestamp) => {
    return format(new Date(timestamp), 'MMM d, yyyy HH:mm:ss');
  };
  
  // Get status code class
  const getStatusCodeClass = (statusCode) => {
    const firstDigit = Math.floor(statusCode / 100);
    switch (firstDigit) {
      case 2:
        return 'bg-green-100 text-green-800';
      case 3:
        return 'bg-blue-100 text-blue-800';
      case 4:
        return 'bg-yellow-100 text-yellow-800';
      case 5:
        return 'bg-red-100 text-red-800';
      default:
        return 'bg-gray-100 text-gray-800';
    }
  };
  
  // Get response time class
  const getResponseTimeClass = (responseTime) => {
    if (responseTime < 100) {
      return 'text-green-600';
    } else if (responseTime < 300) {
      return 'text-blue-600';
    } else if (responseTime < 500) {
      return 'text-yellow-600';
    } else {
      return 'text-red-600';
    }
  };
  
  // Handle time range filter change
  const handleTimeRangeChange = (range) => {
    setTimeRangeFilter(range);
  };
  
  // Handle pagination
  const handlePageChange = (newPage) => {
    setPage(newPage);
  };
  
  // Get current page logs
  const getCurrentLogs = () => {
    const startIndex = (page - 1) * logsPerPage;
    const endIndex = startIndex + logsPerPage;
    return filteredLogs.slice(startIndex, endIndex);
  };
  
  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-blue-500"></div>
      </div>
    );
  }
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-2xl font-semibold text-gray-900">Logs Explorer</h1>
        
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
      
      {/* Filters */}
      <div className="bg-white shadow rounded-lg p-6">
        <h2 className="text-lg font-medium text-gray-900 mb-4">Filters</h2>
        
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <div>
            <label htmlFor="status-filter" className="block text-sm font-medium text-gray-700 mb-1">Status Code</label>
            <select
              id="status-filter"
              className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
            >
              <option value="all">All Status Codes</option>
              <option value="2xx">2xx (Success)</option>
              <option value="3xx">3xx (Redirection)</option>
              <option value="4xx">4xx (Client Error)</option>
              <option value="5xx">5xx (Server Error)</option>
            </select>
          </div>
          
          <div>
            <label htmlFor="endpoint-filter" className="block text-sm font-medium text-gray-700 mb-1">Endpoint</label>
            <input
              type="text"
              id="endpoint-filter"
              className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              placeholder="Filter by endpoint"
              value={endpointFilter}
              onChange={(e) => setEndpointFilter(e.target.value)}
            />
          </div>
          
          <div>
            <label htmlFor="user-id-filter" className="block text-sm font-medium text-gray-700 mb-1">User ID</label>
            <input
              type="text"
              id="user-id-filter"
              className="block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
              placeholder="Filter by user ID"
              value={userIdFilter}
              onChange={(e) => setUserIdFilter(e.target.value)}
            />
          </div>
        </div>
      </div>
      
      {/* Logs table */}
      <div className="bg-white shadow rounded-lg overflow-hidden">
        {error ? (
          <div className="p-4 text-red-700 bg-red-100 rounded-md">{error}</div>
        ) : (
          <>
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Timestamp
                    </th>
                    <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      User ID
                    </th>
                    <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Endpoint
                    </th>
                    <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Status
                    </th>
                    <th scope="col" className="px-6 py-3 text-left text-xs font-medium text-gray-500 uppercase tracking-wider">
                      Response Time
                    </th>
                  </tr>
                </thead>
                <tbody className="bg-white divide-y divide-gray-200">
                  {getCurrentLogs().map((log) => (
                    <tr key={log.id} className="hover:bg-gray-50">
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {formatTimestamp(log.timestamp)}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium text-gray-900">
                        {log.user_id}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm text-gray-500">
                        {log.endpoint}
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap">
                        <span className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium ${getStatusCodeClass(log.status_code)}`}>
                          {log.status_code}
                        </span>
                      </td>
                      <td className="px-6 py-4 whitespace-nowrap text-sm font-medium">
                        <span className={getResponseTimeClass(log.response_time)}>
                          {log.response_time} ms
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            
            {/* Pagination */}
            {totalPages > 1 && (
              <div className="bg-white px-4 py-3 flex items-center justify-between border-t border-gray-200 sm:px-6">
                <div className="hidden sm:flex-1 sm:flex sm:items-center sm:justify-between">
                  <div>
                    <p className="text-sm text-gray-700">
                      Showing <span className="font-medium">{(page - 1) * logsPerPage + 1}</span> to <span className="font-medium">
                        {Math.min(page * logsPerPage, filteredLogs.length)}
                      </span> of <span className="font-medium">{filteredLogs.length}</span> results
                    </p>
                  </div>
                  <div>
                    <nav className="relative z-0 inline-flex rounded-md shadow-sm -space-x-px" aria-label="Pagination">
                      <button
                        onClick={() => handlePageChange(page - 1)}
                        disabled={page === 1}
                        className={`relative inline-flex items-center px-2 py-2 rounded-l-md border border-gray-300 bg-white text-sm font-medium ${page === 1 ? 'text-gray-300 cursor-not-allowed' : 'text-gray-500 hover:bg-gray-50'}`}
                      >
                        Previous
                      </button>
                      
                      {/* Page numbers */}
                      {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                        let pageNum;
                        if (totalPages <= 5) {
                          pageNum = i + 1;
                        } else if (page <= 3) {
                          pageNum = i + 1;
                        } else if (page >= totalPages - 2) {
                          pageNum = totalPages - 4 + i;
                        } else {
                          pageNum = page - 2 + i;
                        }
                        
                        return (
                          <button
                            key={pageNum}
                            onClick={() => handlePageChange(pageNum)}
                            className={`relative inline-flex items-center px-4 py-2 border border-gray-300 bg-white text-sm font-medium ${page === pageNum ? 'z-10 bg-blue-50 border-blue-500 text-blue-600' : 'text-gray-500 hover:bg-gray-50'}`}
                          >
                            {pageNum}
                          </button>
                        );
                      })}
                      
                      <button
                        onClick={() => handlePageChange(page + 1)}
                        disabled={page === totalPages}
                        className={`relative inline-flex items-center px-2 py-2 rounded-r-md border border-gray-300 bg-white text-sm font-medium ${page === totalPages ? 'text-gray-300 cursor-not-allowed' : 'text-gray-500 hover:bg-gray-50'}`}
                      >
                        Next
                      </button>
                    </nav>
                  </div>
                </div>
              </div>
            )}
          </>
        )}
      </div>
    </div>
  );
};

export default LogsExplorer;