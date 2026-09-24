import React from 'react';
import { TIME_RANGES } from '../utils/analytics';

const TimeRangePicker = ({ value, onChange }) => (
  <div className="flex space-x-2" role="group" aria-label="Time range">
    {TIME_RANGES.map((range) => {
      const selected = value === range.value;
      return (
        <button
          key={range.value}
          type="button"
          onClick={() => onChange(range.value)}
          aria-pressed={selected}
          title={`Show the ${range.description}`}
          className={`px-3 py-1 text-sm rounded-md ${
            selected ? 'bg-blue-600 text-white' : 'bg-gray-200 text-gray-700 hover:bg-gray-300'
          }`}
        >
          {range.label}
        </button>
      );
    })}
  </div>
);

export default TimeRangePicker;
