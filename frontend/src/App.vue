<template>
  <div class="container">
    <h1>Restaurant Ordering System</h1>

    <div class="food-list">
      <div class="food-item" v-for="food in foodList" :key="food.id">
        <h3>{{ food.name }}</h3>
        <p>Price: ${{ food.price }}</p >
        <button @click="addToCart(food)">Add to Cart</button>
      </div>
    </div>

    <div class="cart">
      <h2>🛒 Shopping Cart</h2>
      <div v-if="cart.length === 0" class="empty">Your cart is empty</div>
      <div v-for="(item, index) in cart" :key="index" class="cart-item">
        {{ item.name }} × {{ item.count }} = ${{ item.price * item.count }}
        <button @click="reduceCount(index)">-</button>
      </div>
      <div v-if="cart.length > 0" class="total">
        <p>Total: ${{ totalPrice }}</p >
        <button @click="submitOrder">Submit Order</button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

interface Food {
  id: number
  name: string
  price: number
}
interface CartItem extends Food {
  count: number
}

const foodList = ref<Food[]>([
  { id: 1, name: 'Signature Fried Rice', price: 18 },
  { id: 2, name: 'Tomato with Egg', price: 16 },
  { id: 3, name: 'Coke Chicken Wings', price: 28 },
  { id: 4, name: 'Seaweed Egg Soup', price: 8 },
])

const cart = ref<CartItem[]>([])

const addToCart = (food: Food) => {
  const found = cart.value.find(i => i.id === food.id)
  if (found) {
    found.count++
  } else {
    cart.value.push({ ...food, count: 1 })
  }
}

const reduceCount = (index: number) => {
  cart.value[index].count--
  if (cart.value[index].count <= 0) {
    cart.value.splice(index, 1)
  }
}

const totalPrice = computed(() => {
  return cart.value.reduce((sum, item) => sum + item.price * item.count, 0)
})

// 对接后端 /api/v1/orders
const submitOrder = async () => {
  const orderData = {
    items: cart.value,
    total: totalPrice.value
  }
  try {
    const res = await fetch('/api/v1/orders', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json'
      },
      body: JSON.stringify(orderData)
    })
    if (res.ok) {
      alert(`Order submitted successfully! Total: $${totalPrice.value}`)
      cart.value = []
    } else {
      alert('Failed to submit order, please try again.')
    }
  } catch (err) {
    alert('Cannot connect to backend server.')
  }
}
</script>

<style scoped>
.container {
  max-width: 700px;
  margin: 30px auto;
  padding: 0 20px;
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
<!-- test modify 11-->