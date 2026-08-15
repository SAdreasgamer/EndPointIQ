import express from 'express';
import cors from 'cors';
import { userRouter } from './routes/userRoutes';
import { productRouter } from './routes/productRoutes';

const app = express();
app.use(cors());
app.use(express.json());

app.get('/health', (req, res) => { res.json({ status: 'ok' }); });
app.use('/api/users', userRouter);
app.use('/api/products', productRouter);

export default app;
