import { Router } from 'express';

const router = Router();

// All product routes have NO auth at all
router.get('/', (req, res) => { res.json([]); });
router.get('/:id', (req, res) => { res.json({}); });
router.post('/', (req, res) => { res.json(req.body); });

export { router as productRouter };
