<template>
  <div class="dashboard-wrapper">
    <div class="page-header">
      <h2>Business Overview</h2>
    </div>

    <el-row :gutter="20" class="metrics-row">
      <el-col :span="6">
        <el-card shadow="hover" class="metric-card">
          <div class="metric-title">Total Revenue</div>
          <div class="metric-value">${{ overview.total_revenue || '0' }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="metric-card">
          <div class="metric-title">Total Orders</div>
          <div class="metric-value">{{ overview.total_orders || 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="metric-card">
          <div class="metric-title">Avg Turnover</div>
          <div class="metric-value">{{ overview.avg_turnover || 0 }}</div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover" class="metric-card">
          <div class="metric-title">No-show Rate</div>
          <div class="metric-value">{{ ((overview.noshow_rate || 0) * 100).toFixed(1) }}%</div>
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="charts-row">
      <el-col :span="12">
        <div ref="revenueChart" class="chart-container"></div>
      </el-col>
      <el-col :span="12">
        <div ref="turnoverChart" class="chart-container"></div>
      </el-col>
    </el-row>

    <el-row :gutter="20" class="charts-row">
      <el-col :span="24">
        <div ref="heatmapChart" class="chart-container tall-chart"></div>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted, onBeforeUnmount } from 'vue'
import * as echarts from 'echarts'
import axios from 'axios'

const overview = ref({})
const revenueChart = ref(null)
const turnoverChart = ref(null)
const heatmapChart = ref(null)

let chartInstances = []

const fetchDashboardData = async () => {
  try {
    const token = localStorage.getItem('token')
    const headers = { Authorization: `Bearer ${token}` }
    const baseUrl = 'http://localhost:8000/api/v1/analytics'

    const [summaryRes, revenueRes, turnoverRes, heatmapRes] = await Promise.all([
      axios.get(`${baseUrl}/summary`, { headers }),
      axios.get(`${baseUrl}/revenue`, { headers }),
      axios.get(`${baseUrl}/table-turnover`, { headers }),
      axios.get(`${baseUrl}/demand-heatmap`, { headers })
    ])

    overview.value = summaryRes.data.data

    renderRevenueChart(revenueRes.data.data)
    renderTurnoverChart(turnoverRes.data.data)
    renderHeatmapChart(heatmapRes.data.data)

  } catch (error) {
    console.error("Dashboard data fetch failed:", error)
  }
}

const renderRevenueChart = (data) => {
  const chart = echarts.init(revenueChart.value)
  chart.setOption({
    title: { text: 'Revenue Trend', left: 'center' },
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: data.map(item => item.date) },
    yAxis: { type: 'value' },
    series: [{
      data: data.map(item => item.revenue),
      type: 'line',
      smooth: true,
      areaStyle: { opacity: 0.2 },
      itemStyle: { color: '#3b82f6' }
    }]
  })
  chartInstances.push(chart)
}

const renderTurnoverChart = (data) => {
  const chart = echarts.init(turnoverChart.value)
  chart.setOption({
    title: { text: 'Table Turnover Rate', left: 'center' },
    tooltip: { trigger: 'axis' },
    grid: { left: '3%', right: '4%', bottom: '3%', containLabel: true },
    xAxis: { type: 'category', data: data.map(item => item.date) },
    yAxis: { type: 'value' },
    series: [{
      data: data.map(item => item.turnover),
      type: 'bar',
      itemStyle: { color: '#10b981' },
      barWidth: '40%'
    }]
  })
  chartInstances.push(chart)
}

const renderHeatmapChart = (data) => {
  const chart = echarts.init(heatmapChart.value)
  const days = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
  const hours = Array.from({ length: 24 }, (_, i) => `${i}:00`)

  const heatData = data.map(item => [item.hour, item.weekday - 1, item.demand])

  chart.setOption({
    title: { text: 'Hourly Demand Heatmap', left: 'center' },
    tooltip: { position: 'top' },
    grid: { height: '70%', top: '10%' },
    xAxis: { type: 'category', data: hours, splitArea: { show: true } },
    yAxis: { type: 'category', data: days, splitArea: { show: true } },
    visualMap: {
      min: 0,
      max: 120,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: '0%',
      inRange: { color: ['#e0f2fe', '#7dd3fc', '#38bdf8', '#0284c7'] }
    },
    series: [{
      name: 'Demand',
      type: 'heatmap',
      data: heatData,
      label: { show: false },
      emphasis: { itemStyle: { shadowBlur: 10, shadowColor: 'rgba(0, 0, 0, 0.5)' } }
    }]
  })
  chartInstances.push(chart)
}

const handleResize = () => {
  chartInstances.forEach(chart => chart.resize())
}

onMounted(() => {
  fetchDashboardData()
  window.addEventListener('resize', handleResize)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', handleResize)
  chartInstances.forEach(chart => chart.dispose())
  chartInstances = []
})
</script>

<style scoped>
.dashboard-wrapper {
  padding: 24px;
  background-color: #f8fafc;
  min-height: 100vh;
}
.page-header h2 {
  margin-bottom: 24px;
  color: #1e293b;
  font-weight: 600;
}
.metrics-row {
  margin-bottom: 24px;
}
.metric-card {
  text-align: center;
  border-radius: 8px;
}
.metric-title {
  font-size: 14px;
  color: #64748b;
  margin-bottom: 8px;
}
.metric-value {
  font-size: 24px;
  font-weight: 700;
  color: #0f172a;
}
.charts-row {
  margin-bottom: 24px;
}
.chart-container {
  height: 350px;
  background: #ffffff;
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 3px rgba(0, 0, 0, 0.1);
}
.tall-chart {
  height: 420px;
}
</style>