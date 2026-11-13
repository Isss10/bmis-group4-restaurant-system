<template>
  <div class="container">
    <h1>Restaurant Ordering System</h1>

    <!-- Category Filter -->
    <div class="category-bar">
      <button
        v-for="cat in categoryList"
        :key="cat"
        :class="{ active: selectedCategory === cat }"
        @click="selectedCategory = cat"
      >
        {{ cat }}
      </button>
    </div>

    <div class="food-list">
      <div class="food-item" v-for="food in filteredFoodList" :key="food.id">
        <h3>{{ food.name }}</h3>
        <p>Price: ${{ food.price }}</p >
        <p class="category-tag">{{ food.category }}</p >
        <button @click="addToCart(food)">Add to Cart</button>
      </div>
    </div>

    <div class="cart">
      <h2>🛒 Shopping Cart</h2>
      <div v-if="cart.length === 0" class="empty">Your cart is empty</div>
      <div v-for="(item, index) in cart" :key="index" class="cart-item">
        {{ item.name }} × {{ item.count }} = ${{ item.price * item.count }}
        <button @click="reduceCount(index)" :disabled="item.count <= 1">-</button>
      </div>
      <div v-if="cart.length > 0" class="total">
        <p>Total: ${{ totalPrice }}</p >
        <button @click="submitOrder">Submit Order</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import axios from 'axios'
import { ElMessage } from 'element-plus'

interface Food {
  id: number
  name: string
  price: number
  category: string
}
interface CartItem extends Food {
  count: number
}

// Fallback mock menu data with category
const mockFoodList: Food[] = [
  { id: 1, name: 'Signature Fried Rice', price: 18, category: 'Main' },
  { id: 2, name: 'Tomato with Egg', price: 16, category: 'Main' },
  { id: 3, name: 'Coke Chicken Wings', price: 28, category: 'Main' },
  { id: 4, name: 'Seaweed Egg Soup', price: 8, category: 'Soup' },
  { id: 5, name: 'Coca-Cola', price: 4, category: 'Drink' },
  { id: 6, name: 'Spring Rolls', price: 12, category: 'Appetizer' },
]

const foodList = ref<Food[]>([])
const cart = ref<CartItem[]>([])
const selectedCategory = ref<string>('All')

// Get unique category list
const categoryList = computed(() => {
  const cats = new Set(foodList.value.map(f => f.category))
  return ['All', ...cats]
})

// Filter food by selected category
const filteredFoodList = computed(() => {
  if (selectedCategory.value === 'All') return foodList.value
  return foodList.value.filter(f => f.category === selectedCategory.value)
})

// Load menu: request backend api, fallback to mock data for reserved 50001 endpoint
const loadMenu = async () => {
  try {
    const res = await axios.get("/api/v1/orders/menu")
    if (res.data.code === 0) {
      foodList.value = res.data.data
    } else if (res.data.code === 50001) {
      ElMessage.info("Menu API is not implemented, showing local mock data")
      foodList.value = mockFoodList
    }
  } catch (err: any) {
    if (err.response?.data?.code === 50001) {
      ElMessage.info("Menu API is not implemented, showing local mock data")
    }
    foodList.value = mockFoodList
  }
}

const addToCart = (food: Food) => {
  const found = cart.value.find(i => i.id === food.id)
  if (found) {
    found.count++
  } else {
    cart.value.push({ ...food, count: 1 })
  }
}

const reduceCount = (index: number) => {
  const item = cart.value[index]
  item.count--
  if (item.count <= 0) {
    cart.value.splice(index, 1)
  }
}

const totalPrice = computed(() => {
  return cart.value.reduce((sum, item) => sum + item.price * item.count, 0)
})

// Submit order, handle reserved api status code 50001 according to api spec
const submitOrder = async () => {
  if (cart.value.length === 0) {
    ElMessage.warning("Cart is empty, cannot submit order")
    return
  }
  try {
    const submitData = {
      items: cart.value.map(item => ({
        dishId: item.id,
        count: item.count
      }))
    }
    const res = await axios.post("/api/v1/orders", submitData)
    if (res.data.code === 0) {
      ElMessage.success(`Order submitted successfully! Total: $${totalPrice.value}`)
      cart.value = []
    } else if (res.data.code === 50001) {
      ElMessage.warning("Notice: Order API is not implemented, cannot submit order now")
    } else {
      ElMessage.error(`Order failed: ${res.data.message}`)
    }
  } catch (err: any) {
    if (err.response?.data?.code === 50001) {
      ElMessage.warning("Notice: Order API is not implemented, cannot submit order now")
    } else {
      ElMessage.error("Cannot connect to backend server")
    }
  }
}

onMounted(() => {
  loadMenu()
})
</script>

<style scoped>
.container {
  max-width: 700px;
  margin: 30px auto;
  padding: 0 20px;
}
.category-bar {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-bottom: 20px;
}
.category-bar button {
  padding: 6px 12px;
  border: 1px solid #ccc;
  background: #fff;
  border-radius: 6px;
  cursor: pointer;
}
.category-bar button.active {
  background: #222;
  color: white;
  border-color: #222;
}
.food-list {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 30px;
}
.food-item {
  border: 1px solid #ddd;
  padding: 12px;
  border-radius: 8px;
}
.category-tag {
  font-size: 0.8rem;
  color: #666;
  margin:4px 0;
}
.cart {
  border: 1px solid #ccc;
  padding: 16px;
  border-radius: 8px;
}
.cart-item {
  margin: 6px 0;
}
button {
  margin-left: 8px;
  padding: 4px 8px;
  cursor: pointer;
}
</style>