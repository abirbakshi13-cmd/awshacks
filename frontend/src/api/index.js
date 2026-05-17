import * as mocks from './mocks';
import * as client from './client';

// Use mocks unless VITE_USE_MOCKS is explicitly set to "false".
const api = import.meta.env.VITE_USE_MOCKS === 'false' ? client : mocks;

export const { fetchGraph, fetchDigest, saveUser, fetchPrices, sendTestAlert } = api;
