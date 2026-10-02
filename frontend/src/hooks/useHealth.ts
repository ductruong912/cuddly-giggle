import { useCallback, useEffect, useState } from 'react'
import { apiClient } from '@/api/client'
import type { BackendStatus } from '@/types/document'
import type { ReadyzResponse } from '@/types/api'

export function useHealth(pollIntervalMs = 30000) {
  const [status, setStatus] = useState<BackendStatus>('checking')
  const [readiness, setReadiness] = useState<ReadyzResponse | null>(null)
  const [hasPersistence, setHasPersistence] = useState<boolean>(false)
  const [lastChecked, setLastChecked] = useState<Date | null>(null)
  const [errorDetail, setErrorDetail] = useState<string | null>(null)

  const checkHealth = useCallback(async () => {
    try {
      const readyData = await apiClient.getReadiness()
      setReadiness(readyData)
      setLastChecked(new Date())
      setErrorDetail(null)
      setStatus(readyData.status === 'ready' ? 'ready' : 'degraded')

      // Check whether database history is ACTUALLY available
      // Note: /readyz returns database="ok" even when DATABASE_URL is not set (stateless mode).
      // The true test of persistence is whether /v1/extractions is accepted or rejected with 503.
      try {
        await apiClient.getExtractions({ limit: 1 })
        setHasPersistence(true)
      } catch {
        setHasPersistence(false)
      }
    } catch (err: unknown) {
      try {
        await apiClient.getHealth()
        setStatus('degraded')
        setErrorDetail('Liveness OK, but readiness check failed.')
      } catch {
        setStatus('offline')
        setReadiness(null)
        setHasPersistence(false)
        setErrorDetail(err instanceof Error ? err.message : 'Backend unreachable')
      }
      setLastChecked(new Date())
    }
  }, [])

  useEffect(() => {
    let isCancelled = false

    apiClient
      .getReadiness()
      .then((readyData) => {
        if (isCancelled) return
        setReadiness(readyData)
        setLastChecked(new Date())
        setErrorDetail(null)
        setStatus(readyData.status === 'ready' ? 'ready' : 'degraded')

        apiClient
          .getExtractions({ limit: 1 })
          .then(() => {
            if (!isCancelled) setHasPersistence(true)
          })
          .catch(() => {
            if (!isCancelled) setHasPersistence(false)
          })
      })
      .catch(async (err: unknown) => {
        if (isCancelled) return
        try {
          await apiClient.getHealth()
          if (isCancelled) return
          setStatus('degraded')
          setErrorDetail('Liveness OK, but readiness check failed.')
        } catch {
          if (isCancelled) return
          setStatus('offline')
          setReadiness(null)
          setHasPersistence(false)
          setErrorDetail(err instanceof Error ? err.message : 'Backend unreachable')
        }
        setLastChecked(new Date())
      })

    const interval = setInterval(checkHealth, pollIntervalMs)
    return () => {
      isCancelled = true
      clearInterval(interval)
    }
  }, [checkHealth, pollIntervalMs])

  return {
    status,
    readiness,
    hasPersistence,
    lastChecked,
    errorDetail,
    refresh: checkHealth,
  }
}
